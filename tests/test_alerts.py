"""AlertEngine escalation, confidence, and the edge cases that crash real systems."""

from __future__ import annotations

import pytest

from backend.alert_engine import (
    STATUS_INSUFFICIENT,
    STATUS_MONITOR,
    STATUS_PERSISTENT,
    STATUS_RECALIBRATING,
    STATUS_SIGNIFICANT,
    STATUS_STABLE,
    AlertEngine,
)
from ml.anomaly_detector import dual_confirmation
from tests.conftest import make_batch, seed_sessions

engine = AlertEngine()
SCORES = [82.0] * 8


# ---------------------------------------------------------------------------
# escalation ladder
# ---------------------------------------------------------------------------

def test_one_anomaly_in_seven_days_is_stable():
    """We deliberately do not alert after a single bad session. Cognitive
    performance varies with sleep, stress and illness."""
    out = engine.evaluate("u", SCORES, [False] * 6 + [True])
    assert out.status_code == STATUS_STABLE
    assert out.recommend_evaluation is False


def test_two_to_four_anomalies_moves_to_monitor():
    out = engine.evaluate("u", SCORES, [True, True, False, False, False, False, False])
    assert out.status_code == STATUS_MONITOR
    assert out.color == "yellow"


def test_five_anomalies_is_a_significant_deviation():
    out = engine.evaluate("u", SCORES, [True] * 5 + [False, False])
    assert out.status_code == STATUS_SIGNIFICANT
    assert out.color == "orange"
    assert out.recommend_evaluation is False       # still not a referral


def test_a_persistent_declining_trend_is_the_only_referral():
    out = engine.evaluate("u", SCORES, [True] * 4 + [False] * 3, trend_30d="declining")
    assert out.status_code == STATUS_PERSISTENT
    assert out.color == "red"
    assert out.recommend_evaluation is True


def test_a_declining_trend_alone_does_not_escalate():
    """Trend plus persistence, not trend alone."""
    out = engine.evaluate("u", SCORES, [False] * 7, trend_30d="declining")
    assert out.status_code == STATUS_STABLE


# ---------------------------------------------------------------------------
# suppression
# ---------------------------------------------------------------------------

def test_recalibrating_suppresses_every_alert():
    """A new keyboard must never be read as cognitive decline."""
    out = engine.evaluate("u", SCORES, [True] * 7, trend_30d="declining",
                          baseline_status="RECALIBRATING")
    assert out.status_code == STATUS_RECALIBRATING
    assert out.recommend_evaluation is False
    assert out.provisional is True


def test_low_confidence_raises_no_alert():
    """A number without its reliability is a misleading number."""
    out = engine.evaluate("u", SCORES, [True] * 7, trend_30d="declining",
                          confidence_band="LOW")
    assert out.status_code == STATUS_INSUFFICIENT
    assert out.provisional is True
    assert out.recommend_evaluation is False


def test_too_few_scores_is_insufficient_data():
    out = engine.evaluate("u", [80.0], [False])
    assert out.status_code == STATUS_INSUFFICIENT
    assert out.provisional is True


def test_no_data_at_all_is_handled():
    out = engine.evaluate("u", [], [])
    assert out.status_code == STATUS_INSUFFICIENT


# ---------------------------------------------------------------------------
# presentation — colour is never the only channel
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("anomalies,trend", [
    ([False] * 7, None), ([True, True] + [False] * 5, None),
    ([True] * 5 + [False, False], None), ([True] * 4 + [False] * 3, "declining"),
])
def test_every_state_carries_a_label_and_an_icon(anomalies, trend):
    out = engine.evaluate("u", SCORES, anomalies, trend_30d=trend)
    assert out.label and out.icon and out.color
    assert out.user_message


@pytest.mark.parametrize("anomalies,trend", [
    ([False] * 7, None), ([True] * 5 + [False, False], None),
    ([True] * 4 + [False] * 3, "declining"),
])
def test_no_message_uses_diagnostic_language(anomalies, trend):
    """The strongest thing CogniDiff will ever say is 'worth a professional
    opinion'. It never names a condition."""
    text = engine.evaluate("u", SCORES, anomalies, trend_30d=trend).user_message.lower()
    for word in ("alzheimer", "dementia", "mci", "diagnos", "disease",
                 "impairment", "decline"):
        assert word not in text, f"diagnostic language: {word!r} in {text!r}"


def test_alert_serialises_for_the_api():
    payload = engine.evaluate("u", SCORES, [False] * 7).as_dict()
    assert set(payload) >= {"status_code", "color", "label", "icon",
                            "user_message", "recommend_evaluation", "provisional"}


# ---------------------------------------------------------------------------
# dual confirmation
# ---------------------------------------------------------------------------

def test_both_models_must_agree_to_flag():
    assert dual_confirmation(40.0, {"is_anomaly": True})["concerning"] is True


def test_statistics_alone_does_not_flag():
    out = dual_confirmation(40.0, {"is_anomaly": False})
    assert out["concerning"] is False
    assert out["agreement"] == "MODELS_DISAGREE"


def test_the_forest_alone_does_not_flag():
    out = dual_confirmation(5.0, {"is_anomaly": True})
    assert out["concerning"] is False
    assert out["agreement"] == "MODELS_DISAGREE"


def test_agreement_on_normal_is_reported():
    assert dual_confirmation(5.0, {"is_anomaly": False})["agreement"] == "BOTH_AGREE_NORMAL"


def test_a_missing_anomaly_result_never_flags():
    assert dual_confirmation(90.0, None)["concerning"] is False


# ---------------------------------------------------------------------------
# API-level edge cases
# ---------------------------------------------------------------------------

def test_zero_sessions_returns_a_helpful_state_not_a_crash(client, user):
    body = client.get("/api/dashboard/me", headers=user["headers"]).json()
    assert body["status"] in ("NO_DATA", "INSUFFICIENT_DATA")
    assert body["current_score"] is None
    assert body["message"]


def test_exactly_one_session_does_not_produce_a_score(client, user):
    client.post("/api/session", json=make_batch(), headers=user["headers"])
    body = client.get("/api/dashboard/me", headers=user["headers"]).json()
    assert body["current_score"] is None


def test_fitting_a_baseline_too_early_is_a_clean_400(client, user):
    seed_sessions(client, user["headers"], n=3)
    res = client.post("/api/baseline/fit", json=None, headers=user["headers"])
    assert res.status_code == 400
    assert "at least" in res.json()["detail"]


def test_a_duplicate_session_is_stored_not_merged(client, user):
    payload = make_batch(seed=7)
    for _ in range(2):
        assert client.post("/api/session", json=payload, headers=user["headers"]).status_code == 201
    assert client.get("/api/sessions/me", headers=user["headers"]).json()["count"] == 2


def test_the_quality_endpoint_reports_a_real_exclusion_rate(client, user):
    seed_sessions(client, user["headers"], n=8)
    for i in range(2):
        client.post("/api/session", json=make_batch(keystrokes=4, duration_ms=3000, seed=100 + i),
                    headers=user["headers"])

    body = client.get("/api/sessions/quality", headers=user["headers"]).json()
    assert body["total_sessions"] == 10
    assert body["sessions_excluded_quality"] >= 2
    assert body["exclusion_rate_percent"] > 0
    assert any(r["reason_code"] == "LOW_VOLUME" for r in body["reason_breakdown"])


def test_confidence_falls_when_evidence_is_thin(client, user, seeded_user):
    body = client.get("/api/dashboard/me", headers=seeded_user["headers"]).json()
    assert 0 <= body["confidence"] <= 100
    assert body["confidence_band"] in ("HIGH", "MODERATE", "LOW")
    assert set(body["confidence_breakdown"]) == {
        "session_count", "session_quality", "baseline_size",
        "model_agreement", "context_available", "feature_completeness",
    }


def test_task_scores_blend_into_the_composite(client, seeded_user):
    before = client.get("/api/dashboard/me", headers=seeded_user["headers"]).json()
    assert before["task_score"] is None
    assert before["composite_weighting"] == "keystroke_only"

    res = client.post("/api/task-score", headers=seeded_user["headers"], json={
        "word_recall": 5, "reaction_time_ms": 300,
        "pattern_memory": 5, "letter_scramble_ms": 3500,
    })
    assert res.status_code == 201

    after = client.get("/api/dashboard/me", headers=seeded_user["headers"]).json()
    assert after["task_score"] is not None
    assert "keystroke/task" in after["composite_weighting"]


def test_an_empty_task_submission_is_refused(client, user):
    assert client.post("/api/task-score", json={}, headers=user["headers"]).status_code == 422


def test_context_out_of_range_is_refused(client, user):
    assert client.post("/api/context", json={"stress_level": 9},
                       headers=user["headers"]).status_code == 422
    assert client.post("/api/context", json={"sleep_quality": 0},
                       headers=user["headers"]).status_code == 422


def test_reporting_a_device_change_starts_recalibration(client, seeded_user):
    client.post("/api/context", json={"device_changed": True}, headers=seeded_user["headers"])
    me = client.get("/api/auth/me", headers=seeded_user["headers"]).json()
    assert me["baseline_status"] == "RECALIBRATING"

    body = client.get("/api/dashboard/me", headers=seeded_user["headers"]).json()
    assert body["alert_status"]["status_code"] == "RECALIBRATING"
    assert body["provisional"] is True


def test_every_stored_score_carries_its_four_version_fields(client, seeded_user):
    from backend import database as db

    client.post("/api/score", json={"recompute": True}, headers=seeded_user["headers"])
    row = db.query_one(
        "SELECT * FROM cogniscores WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (seeded_user["user_id"],),
    )
    for field in ("model_version", "baseline_version",
                  "feature_schema_version", "code_commit"):
        assert row[field] not in (None, ""), f"{field} missing"
