"""Shared pytest fixtures.

Every test runs against a temporary SQLite file and a temporary model
directory. Nothing here ever touches the real cognidiff.db or the real
ml/models — a test suite that can corrupt live health data is not a safety net,
it is a second hazard.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import config, database as db          # noqa: E402
from backend.ratelimit import limiter               # noqa: E402


# ---------------------------------------------------------------------------
# isolation
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Point the whole stack at a throwaway database and model directory."""
    db_file = tmp_path / "test.db"
    models = tmp_path / "models"
    models.mkdir()

    db.set_db_path(db_file)
    monkeypatch.setattr(config, "MODEL_DIR", models)

    # ml modules captured MODEL_DIR at import time
    import ml.baseline, ml.anomaly_detector, ml.lstm_model, ml.xgb_model
    for module in (ml.baseline, ml.anomaly_detector, ml.lstm_model, ml.xgb_model):
        monkeypatch.setattr(module, "MODEL_DIR", models, raising=False)

    db.init_db()
    yield db_file

    db.set_db_path(config.DB_PATH)


@pytest.fixture(autouse=True)
def clean_limiter():
    """Rate limiting off by default — it is exercised explicitly in its own
    test, and left on everywhere else it would make the suite order-dependent."""
    limiter.reset()
    limiter.enabled = False
    yield
    limiter.reset()
    limiter.enabled = False


@pytest.fixture
def client():
    from backend.main import app
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# accounts
# ---------------------------------------------------------------------------

PASSWORD = "test-password-123"


def _register(client, username, role="USER", first_name=None):
    res = client.post("/api/auth/register", json={
        "username": username, "password": PASSWORD,
        "role": role, "first_name": first_name,
    })
    assert res.status_code == 201, res.text
    return res.json()


@pytest.fixture
def user(client):
    out = _register(client, "alice", "USER", "Alice")
    return {**out, "headers": {"Authorization": f"Bearer {out['access_token']}"}}


@pytest.fixture
def other_user(client):
    out = _register(client, "bob", "USER", "Bob")
    return {**out, "headers": {"Authorization": f"Bearer {out['access_token']}"}}


@pytest.fixture
def doctor(client):
    out = _register(client, "dr.who", "DOCTOR", "Who")
    return {**out, "headers": {"Authorization": f"Bearer {out['access_token']}"}}


# ---------------------------------------------------------------------------
# synthetic sessions
# ---------------------------------------------------------------------------

def make_batch(
    wpm=60.0, iki=180.0, hold=88.0, error_rate=0.04,
    keystrokes=280, duration_ms=58_000, on_date=None, hour=10,
    device="Windows|md|en", seed=0,
) -> dict:
    """A well-formed batch that passes the quality gate."""
    rng = np.random.default_rng(seed)

    cats, offsets = [], []
    t = 0.0
    for _ in range(keystrokes):
        t += max(15.0, rng.normal(iki, iki * 0.45))
        if t > duration_ms:
            break
        offsets.append(round(t, 1))
        roll = rng.random()
        cats.append("b" if roll < error_rate
                    else "s" if roll < error_rate + 0.16
                    else "p" if roll < error_rate + 0.20
                    else "l")

    intervals = [round(offsets[i] - offsets[i - 1], 1) for i in range(1, len(offsets))]

    return {
        "wpm_estimate": round(wpm, 2),
        "avg_inter_key_interval_ms": round(float(np.mean(intervals)) if intervals else iki, 2),
        "avg_hold_duration_ms": round(hold, 2),
        "backspace_count": cats.count("b"),
        "total_keystrokes": len(cats),
        "pause_count": sum(1 for i in intervals if i > 2000),
        "long_pause_count": sum(1 for i in intervals if i > 3000),
        "session_minute": 0,
        "duration_ms": int(min(t, duration_ms)),
        "key_categories": "".join(cats),
        "offsets_ms": offsets,
        "intervals_ms": intervals,
        "device_fingerprint": device,
        "date": (on_date or date.today()).isoformat(),
        "hour": hour,
        "complete": True,
    }


@pytest.fixture
def batch_factory():
    return make_batch


def seed_sessions(client, headers, n=14, days_back=14, **kwargs) -> int:
    """POST `n` good sessions spread over the past `days_back` days.

    Dates ascend and the last session lands on today, matching how sessions
    actually arrive. Insertion order and date order have to agree, because the
    scorer picks the most recently *received* session and then reads its date —
    shuffled fixtures would score a fortnight-old session as 'today'.
    """
    stored = 0
    for i in range(n):
        day = date.today() - timedelta(days=max(0, days_back - 1 - i))
        payload = make_batch(on_date=day, hour=9 + (i % 8), seed=i, **kwargs)
        res = client.post("/api/session", json=payload, headers=headers)
        assert res.status_code == 201, res.text
        stored += 1
    return stored


@pytest.fixture
def seeded_user(client, user):
    """A user with a fitted baseline and anomaly detector."""
    seed_sessions(client, user["headers"], n=16)
    assert client.post("/api/baseline/fit", json=None, headers=user["headers"]).status_code == 200
    assert client.post("/api/anomaly/fit", json=None, headers=user["headers"]).status_code == 200
    return user
