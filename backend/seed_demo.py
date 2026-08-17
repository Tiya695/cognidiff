"""Seed a demonstrable CogniDiff instance.

Generates a realistic history for one user: a settled baseline period, then a
recent stretch with a mild, gradual shift so the trend, the alert engine and the
explanation all have something true to say. Also creates a doctor account with
an active consent grant so the clinician path can be demonstrated end to end.

    python -m backend.seed_demo [--days 75] [--reset]

The generated sessions are SYNTHETIC. They exist to demonstrate the pipeline,
not to evidence anything about a real person — see docs/ground_truth_strategy.md.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta

import numpy as np

from . import database as db
from .auth import create_user
from .config import set_all_seeds, SEED
from .data_quality import DataQualityEngine
from .features import enrich_batch
from . import scoring

USER = {"username": "tiya", "password": "cognidiff2026", "first_name": "Tiya"}
DOCTOR = {"username": "dr.mehta", "password": "cognidiff2026", "first_name": "Anjali"}

HOURS = [9, 11, 14, 16, 20]


def _synth_batch(rng, day: date, hour: int, drift: float, degraded: bool) -> dict:
    """One 60-second batch. `drift` 0..1 scales a mild adverse shift."""
    # Personal baseline constants — this is "Tiya's" normal.
    wpm = 62.0 - 9.0 * drift
    iki = 178.0 + 46.0 * drift
    hold = 88.0 + 9.0 * drift
    err = 0.041 + 0.030 * drift
    rhythm = 96.0 + 44.0 * drift

    # Time-of-day effect: late-night typing is genuinely slower for most people,
    # which is exactly why baselines are also fitted per time slot.
    if hour >= 20:
        wpm -= 3.0; iki += 14.0
    elif hour <= 9:
        wpm -= 1.2; iki += 5.0

    if degraded:
        wpm *= 0.72; iki *= 1.45; err *= 2.3; rhythm *= 1.7

    wpm = max(8.0, rng.normal(wpm, 4.2))
    iki = max(60.0, rng.normal(iki, 16.0))
    hold = max(30.0, rng.normal(hold, 6.5))
    err = float(np.clip(rng.normal(err, 0.012), 0.002, 0.35))
    rhythm = max(20.0, rng.normal(rhythm, 14.0))

    total = int(np.clip(rng.normal(wpm * 5, 30), 45, 900))
    backspaces = int(np.clip(total * err, 1, total - 1))

    # Build a plausible category/timing sequence so correction-event detection
    # and the quality gate have real material to work on.
    cats, offsets = [], []
    t = 0.0
    for i in range(total):
        gap = max(12.0, rng.normal(iki, rhythm))
        t += gap
        if t > 59_000:
            break
        offsets.append(round(t, 1))
        roll = rng.random()
        if roll < err:
            cats.append("b")
        elif roll < err + 0.16:
            cats.append("s")
        elif roll < err + 0.20:
            cats.append("p")
        elif roll < err + 0.215:
            cats.append("d")
        else:
            cats.append("l")

    n = len(cats)
    intervals = [round(offsets[i] - offsets[i - 1], 1) for i in range(1, n)]

    return {
        "wpm_estimate": round((n / 5) / max(t / 60_000, 1 / 60), 2),
        "avg_inter_key_interval_ms": round(float(np.mean(intervals)) if intervals else iki, 2),
        "avg_hold_duration_ms": round(hold, 2),
        "backspace_count": cats.count("b"),
        "total_keystrokes": n,
        "pause_count": sum(1 for i in intervals if i > 2000),
        "long_pause_count": sum(1 for i in intervals if i > 3000),
        "session_minute": 0,
        "duration_ms": int(t),
        "key_categories": "".join(cats),
        "offsets_ms": offsets,
        "intervals_ms": intervals,
        "device_fingerprint": "Windows|md|en",
        "date": day.isoformat(),
        "hour": hour,
        "complete": True,
    }


def _store(user: dict, batch: dict) -> int:
    enriched = enrich_batch(batch)
    enriched["key_categories"] = batch["key_categories"]
    enriched["complete"] = batch["complete"]

    quality = DataQualityEngine(baseline_device=user.get("baseline_device")) \
        .score_session(enriched)

    session_id = db.insert("keystroke_sessions", {
        "user_id": user["id"], "date": batch["date"], "hour": enriched["hour"],
        "wpm_estimate": enriched["wpm_estimate"],
        "avg_iki_ms": enriched["avg_iki_ms"],
        "avg_hold_ms": enriched["avg_hold_ms"],
        "backspace_count": enriched["backspace_count"],
        "total_keystrokes": enriched["total_keystrokes"],
        "pause_count": enriched["pause_count"],
        "session_minute": enriched["session_minute"],
        "error_rate": enriched["error_rate"],
        "correction_rate": enriched["correction_rate"],
        "correction_events": enriched["correction_events"],
        "mean_keys_deleted": enriched["mean_keys_deleted"],
        "mean_correction_ms": enriched["mean_correction_ms"],
        "rhythm_variability": enriched["rhythm_variability"],
        "long_pause_count": enriched["long_pause_count"],
        "burst_ratio": enriched["burst_ratio"],
        "time_slot": enriched["time_slot"],
        "duration_ms": enriched["duration_ms"],
        "device_fingerprint": enriched["device_fingerprint"],
        "quality_score": quality.quality_score,
        "excluded": int(quality.should_exclude),
        "device_changed": int(quality.device_changed),
        "created_at": datetime.combine(
            date.fromisoformat(batch["date"]),
            datetime.min.time()
        ).replace(hour=enriched["hour"]).isoformat(timespec="seconds"),
    })

    for code in quality.reason_codes:
        db.insert("session_exclusions", {
            "session_id": session_id, "user_id": user["id"], "date": batch["date"],
            "reason_code": code, "detail": code, "created_at": db.utcnow(),
        })
    return session_id


def _ensure_user(spec: dict, role: str) -> dict:
    existing = db.get_user_by_username(spec["username"])
    if existing:
        return existing
    return create_user(spec["username"], spec["password"], role, spec["first_name"])


def main(days: int = 75, reset: bool = False) -> None:
    set_all_seeds(SEED)
    rng = np.random.default_rng(SEED)
    db.init_db()

    user = _ensure_user(USER, "USER")
    doctor = _ensure_user(DOCTOR, "DOCTOR")

    if reset:
        db.delete_user_data(user["id"])
        print("cleared existing data for", USER["username"])

    existing = db.query_one(
        "SELECT COUNT(*) AS n FROM keystroke_sessions WHERE user_id = ?", (user["id"],)
    )
    if existing and existing["n"] > 0 and not reset:
        print(f"{USER['username']} already has {existing['n']} sessions — "
              f"pass --reset to regenerate.")
        return

    today = date.today()
    print(f"generating {days} days of sessions …")

    total_sessions = 0
    for offset in range(days, 0, -1):
        day = today - timedelta(days=offset - 1)

        # Baseline period is flat. A gradual, mild adverse shift begins in the
        # final third — the sort of change CogniDiff exists to notice.
        progress = max(0.0, (days - offset - days * 0.62) / (days * 0.38))
        # Kept mild on purpose. The demo should land in the graded MONITOR /
        # SIGNIFICANT band, not slam into the red — a tool that only ever
        # demonstrates its most alarming state teaches the wrong thing about it.
        drift = float(np.clip(progress, 0, 1)) * 0.38

        # people do not type every day
        if rng.random() < 0.12:
            continue

        for hour in HOURS:
            if rng.random() < 0.42:
                continue
            # occasional genuinely bad session (tiredness, interruption)
            degraded = rng.random() < (0.05 + 0.10 * drift)
            _store(user, _synth_batch(rng, day, hour, drift, degraded))
            total_sessions += 1

        # a couple of deliberately unusable sessions, so the quality gate has a
        # real, non-zero exclusion rate to report
        if rng.random() < 0.10:
            junk = _synth_batch(rng, day, 13, drift, False)
            junk.update(total_keystrokes=6, key_categories="lldsb",
                        offsets_ms=[10, 220, 480, 900, 1400],
                        intervals_ms=[210, 260, 420, 500], duration_ms=4200,
                        complete=False)
            _store(user, junk)
            total_sessions += 1

    print(f"  {total_sessions} sessions stored")

    print("fitting baseline …")
    print("  ", scoring.fit_baseline(user["id"])["summary"]["n_sessions"], "sessions used")

    print("fitting anomaly detector …")
    scoring.fit_anomaly(user["id"])

    print("scoring each day …")
    days_scored = 0
    rows = db.query(
        "SELECT DISTINCT date FROM keystroke_sessions "
        "WHERE user_id = ? AND excluded = 0 ORDER BY date ASC",
        (user["id"],),
    )
    for r in rows:
        # Score up to three sessions per day rather than just the last one. A
        # daily figure resting on a single session swings wildly whenever that
        # session happened to be a distracted one — the dashboard then shows a
        # cliff that means nothing. Averaging the day is both steadier and a
        # more honest summary of it.
        sessions = db.query(
            "SELECT * FROM keystroke_sessions WHERE user_id = ? AND date = ? "
            "AND excluded = 0 ORDER BY id ASC",
            (user["id"], r["date"]),
        )
        if not sessions:
            continue

        if len(sessions) > 3:
            step = len(sessions) / 3.0
            sessions = [sessions[int(i * step)] for i in range(3)]

        scored_any = False
        for session in sessions:
            try:
                result = scoring.score_user(user["id"], session=session, persist=False)
                if result["status"] == "OK":
                    scoring._persist(user["id"], r["date"], result)
                    scored_any = True
            except Exception as exc:
                print("   skipped", r["date"], type(exc).__name__)
        if scored_any:
            days_scored += 1
    print(f"  {days_scored} days scored")

    print("training trend model …")
    try:
        info = scoring.fit_lstm(user["id"])
        print(f"  backend={info['backend']} beats_naive={info['evaluation'].get('beats_naive')}")
    except ValueError as exc:
        print("  skipped:", exc)

    # exploratory pseudo-label model, for the feature-importance comparison
    try:
        from ml.anomaly_detector import AnomalyDetector
        from ml.xgb_model import XGBCogniClassifier
        sessions = db.good_sessions(user["id"])
        detector = AnomalyDetector.load(user["id"])
        labels = [detector.predict(s)["is_anomaly"] for s in sessions]
        XGBCogniClassifier(user["id"]).train(sessions, labels)
        XGBCogniClassifier.load(user["id"])
        model = XGBCogniClassifier(user["id"])
        model.train(sessions, labels)
        model.save()
        print("  exploratory pseudo-label model trained")
    except Exception as exc:
        print("  exploratory model skipped:", type(exc).__name__, exc)

    if not db.has_active_consent(user["id"], doctor["id"]):
        db.insert("consent_grants", {
            "user_id": user["id"], "granted_to": doctor["id"],
            "granted_at": db.utcnow(), "revoked_at": None, "active": 1,
        })
        print("consent granted to", DOCTOR["username"])

    print("\nDone. Sign in at http://localhost:3000/pages/login.html")
    print(f"  USER    {USER['username']} / {USER['password']}")
    print(f"  DOCTOR  {DOCTOR['username']} / {DOCTOR['password']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed CogniDiff demo data.")
    parser.add_argument("--days", type=int, default=75)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    sys.exit(main(args.days, args.reset))
