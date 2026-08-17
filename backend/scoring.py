"""Scoring orchestration.

This is the only place a CogniScore is produced, and it runs **server-side
only**. There is no endpoint anywhere in CogniDiff that accepts a score from a
client. The client sends behavioural features; the server derives everything
else from stored data. The score is the most valuable asset in the system, so it
must be unforgeable, that property is what Attack 12 tests.
"""

from __future__ import annotations

from datetime import date as _date
from typing import Optional

from . import database as db
from .alert_engine import AlertEngine
from .config import (
    BASELINE_WINDOW_DAYS,
    KEYSTROKE_WEIGHT,
    MIN_BASELINE_SESSIONS,
    QUALITY_EXCLUDE_THRESHOLD,
    TASK_WEIGHT,
    version_fields,
)
from .context_tracker import ContextTracker
from ml.anomaly_detector import AnomalyDetector, dual_confirmation
from ml.baseline import PersonalBaseline
from ml.explainer import CogniExplainer, format_explanation
from ml.lstm_model import LSTMPredictor

# ---------------------------------------------------------------------------
# confidence
# ---------------------------------------------------------------------------

#: Six components, weighted. A number without its reliability is a misleading
#: number in a health tool, so every score carries one of these.
CONFIDENCE_WEIGHTS = {
    "session_count": 0.20,      # how many quality sessions today
    "session_quality": 0.20,    # how good they were
    "baseline_size": 0.20,      # how well established the baseline is
    "model_agreement": 0.15,    # do the two detectors agree
    "context_available": 0.10,  # did the user tell us about today
    "feature_completeness": 0.15,
}


def compute_confidence(user_id: str, on_date: Optional[str] = None) -> dict:
    """Return ``{confidence, band, breakdown}`` for a user's day."""
    day = on_date or _date.today().isoformat()

    todays = db.query(
        "SELECT * FROM keystroke_sessions "
        "WHERE user_id = ? AND date = ? AND excluded = 0",
        (user_id, day),
    )
    all_good = db.good_sessions(user_id)

    parts: dict[str, float] = {}

    # 1. How many usable sessions today. 6+ is a full day of evidence.
    parts["session_count"] = min(100.0, len(todays) / 6.0 * 100.0)

    # 2. How good they were.
    parts["session_quality"] = (
        sum(float(s.get("quality_score", 0) or 0) for s in todays) / len(todays)
        if todays else 0.0
    )

    # 3. How well established the baseline is. 30 sessions is a settled baseline.
    parts["baseline_size"] = min(100.0, len(all_good) / 30.0 * 100.0)

    # 4. Do the statistical and ML detectors agree on today's sessions?
    parts["model_agreement"] = _agreement_score(user_id, todays)

    # 5. Did the user log context today?
    parts["context_available"] = 100.0 if ContextTracker.get(user_id, day) else 40.0

    # 6. Feature completeness across today's sessions.
    parts["feature_completeness"] = _completeness_score(todays)

    confidence = sum(parts[k] * CONFIDENCE_WEIGHTS[k] for k in CONFIDENCE_WEIGHTS)
    confidence = round(max(0.0, min(100.0, confidence)), 1)

    band = "HIGH" if confidence > 75 else "MODERATE" if confidence >= 50 else "LOW"

    return {
        "confidence": confidence,
        "band": band,
        "breakdown": {k: round(v, 1) for k, v in parts.items()},
        "sessions_today": len(todays),
        "baseline_sessions": len(all_good),
    }


def _agreement_score(user_id: str, sessions: list[dict]) -> float:
    if not sessions:
        return 0.0
    baseline = PersonalBaseline.load(user_id)
    detector = AnomalyDetector.load(user_id)
    if baseline is None or detector is None or not detector.is_fitted:
        return 50.0                       # can't tell, neutral, not confident

    agree = 0
    for s in sessions:
        try:
            dev = baseline.overall_deviation(s)
            anomaly = detector.predict(s)
            verdict = dual_confirmation(dev, anomaly)
            if verdict["agreement"] in ("BOTH_AGREE_NORMAL", "BOTH_AGREE_ANOMALOUS"):
                agree += 1
        except Exception:
            continue
    return round(100.0 * agree / len(sessions), 1)


def _completeness_score(sessions: list[dict]) -> float:
    if not sessions:
        return 0.0
    fields = ("wpm_estimate", "avg_iki_ms", "avg_hold_ms", "error_rate",
              "correction_rate", "rhythm_variability", "burst_ratio")
    total = len(sessions) * len(fields)
    present = sum(
        1 for s in sessions for f in fields
        if s.get(f) is not None
    )
    return round(100.0 * present / total, 1)


# ---------------------------------------------------------------------------
# the full scoring pipeline
# ---------------------------------------------------------------------------

def score_user(
    user_id: str,
    session: Optional[dict] = None,
    persist: bool = True,
) -> dict:
    """Run the whole pipeline for a user's most recent session.

    Order matters: quality gate → baseline deviation → CogniScore → anomaly →
    dual confirmation → explanation → context adjustment → composite with task
    scores → confidence → alert. Each stage can only narrow what the next one is
    allowed to claim.
    """
    user = db.get_user(user_id)
    if user is None:
        raise ValueError("unknown user")

    session = session or db.latest_session(user_id)
    if session is None:
        return {
            "status": "NO_DATA",
            "message": "No quality-passing sessions yet. Type for a few minutes "
                       "with monitoring on and check back.",
            "cogni_score": None,
        }

    baseline = PersonalBaseline.load(user_id)
    if baseline is None or not baseline.is_fitted:
        good = db.good_sessions(user_id)
        return {
            "status": "INSUFFICIENT_DATA",
            "message": (
                f"Building your baseline, {len(good)} of {MIN_BASELINE_SESSIONS} "
                f"quality sessions collected."
            ),
            "cogni_score": None,
            "baseline_sessions": len(good),
            "baseline_required": MIN_BASELINE_SESSIONS,
        }

    day = session.get("date") or _date.today().isoformat()

    # --- baseline deviation + CogniScore ----------------------------------
    scored = baseline.cogni_score(session)

    # --- anomaly detection + dual confirmation ----------------------------
    detector = AnomalyDetector.load(user_id)
    anomaly = None
    if detector is not None and detector.is_fitted:
        try:
            anomaly = detector.predict(session)
        except Exception:
            anomaly = None
    verdict = dual_confirmation(scored["deviation_percent"], anomaly)

    # --- explanation -------------------------------------------------------
    top_3: list[dict] = []
    explain_method = "none"
    if detector is not None and detector.is_fitted:
        try:
            explainer = CogniExplainer(detector).fit(db.good_sessions(user_id))
            top_3 = format_explanation(
                explainer.explain(session), scored["per_feature"], top_n=3
            )
            explain_method = explainer.method
        except Exception:
            top_3 = []
    if not top_3:
        # Fall back to the baseline's own ranking so the user always gets a
        # reason, even when the explainer could not run.
        ranked = sorted(
            scored["per_feature"].items(),
            key=lambda kv: kv[1]["adverse_z"], reverse=True,
        )[:3]
        top_3 = format_explanation(
            [{"feature": f, "direction": d["direction"], "shap_value": None}
             for f, d in ranked],
            scored["per_feature"], top_n=3,
        )
        explain_method = "baseline_ranking"

    # --- context adjustment ------------------------------------------------
    context = ContextTracker.get(user_id, day)
    adjusted = ContextTracker.adjust_score(scored["cogni_score"], context)

    # --- composite with today's active tasks -------------------------------
    composite = _composite(user_id, day, adjusted["adjusted_score"])

    # --- confidence --------------------------------------------------------
    conf = compute_confidence(user_id, day)

    # --- trend + alert -----------------------------------------------------
    trend = _trend_direction(user_id)
    recent = db.query(
        "SELECT adjusted_score, is_anomaly FROM cogniscores "
        "WHERE user_id = ? ORDER BY id DESC LIMIT 7",
        (user_id,),
    )
    recent_scores = [r["adjusted_score"] for r in reversed(recent)]
    recent_anoms = [bool(r["is_anomaly"]) for r in reversed(recent)]
    recent_scores.append(composite["score"])
    recent_anoms.append(verdict["concerning"])

    alert = AlertEngine().evaluate(
        user_id=user_id,
        recent_scores=recent_scores,
        recent_anomalies=recent_anoms,
        trend_30d=trend,
        baseline_status=user.get("baseline_status", "ACTIVE"),
        confidence_band=conf["band"],
    )

    provisional = alert.provisional or conf["band"] == "LOW"

    result = {
        "status": "OK",
        "date": day,
        "cogni_score": composite["score"],
        "raw_score": adjusted["raw_score"],
        "adjusted_score": adjusted["adjusted_score"],
        "composite_score": composite["score"],
        "keystroke_score": adjusted["adjusted_score"],
        "task_score": composite["task_score"],
        "composite_weighting": composite["weighting"],
        "deviation_percent": scored["deviation_percent"],
        "top_deviating_feature": scored["top_deviating_feature"],
        "per_feature": scored["per_feature"],
        "top_3_changes": top_3,
        "explanation_method": explain_method,
        "anomaly": anomaly,
        "dual_confirmation": verdict,
        "context": {**adjusted, "reported": context is not None},
        "confidence": conf["confidence"],
        "confidence_band": conf["band"],
        "confidence_breakdown": conf["breakdown"],
        "alert": alert.as_dict(),
        "provisional": provisional,
        "quality_score": float(session.get("quality_score", 0) or 0),
        "time_slot_used": scored["time_slot_used"],
        "baseline_status": user.get("baseline_status", "ACTIVE"),
        **version_fields(int(user.get("baseline_version", 1) or 1)),
    }

    if persist:
        _persist(user_id, day, result)

    return result


def _composite(user_id: str, day: str, keystroke_score: float) -> dict:
    """Blend passive keystroke monitoring with today's active mini-tasks.

    Keystroke-only when no task scores exist for the day, an absent task is not
    a zero.
    """
    row = db.query_one(
        "SELECT composite_task_score FROM task_results "
        "WHERE user_id = ? AND date = ? ORDER BY id DESC LIMIT 1",
        (user_id, day),
    )
    if row is None or row["composite_task_score"] is None:
        return {
            "score": round(float(keystroke_score), 1),
            "task_score": None,
            "weighting": "keystroke_only",
        }

    task_score = float(row["composite_task_score"])
    blended = KEYSTROKE_WEIGHT * float(keystroke_score) + TASK_WEIGHT * task_score
    return {
        "score": round(blended, 1),
        "task_score": round(task_score, 1),
        "weighting": f"{KEYSTROKE_WEIGHT:.0%}/{TASK_WEIGHT:.0%} keystroke/task",
    }


def _trend_direction(user_id: str, days: int = 30) -> str:
    rows = db.query(
        "SELECT date, AVG(adjusted_score) AS s FROM cogniscores "
        "WHERE user_id = ? AND date >= date('now', 'localtime', ?) "
        "GROUP BY date ORDER BY date ASC",
        (user_id, f"-{days} day"),
    )
    scores = [r["s"] for r in rows if r["s"] is not None]
    if len(scores) < 5:
        return "insufficient_data"

    half = len(scores) // 2
    early = sum(scores[:half]) / half
    late = sum(scores[half:]) / (len(scores) - half)
    delta = late - early

    if delta < -4:
        return "declining"
    if delta > 4:
        return "improving"
    return "stable"


def _persist(user_id: str, day: str, result: dict) -> int:
    """Write the score. Only this function writes to cogniscores, there is no
    endpoint that updates a score directly."""
    return db.insert("cogniscores", {
        "user_id": user_id,
        "date": day,
        "raw_score": result["raw_score"],
        "adjusted_score": result["adjusted_score"],
        "composite_score": result["composite_score"],
        "top_deviating_feature": result["top_deviating_feature"],
        "deviation_percent": result["deviation_percent"],
        "quality_score": result["quality_score"],
        "confidence": result["confidence"],
        "confidence_band": result["confidence_band"],
        "context_adjusted": int(bool(result["context"]["context_adjusted"])),
        "is_anomaly": int(bool(result["dual_confirmation"]["concerning"])),
        "anomaly_score": float((result.get("anomaly") or {}).get("anomaly_score", 0)),
        "alert_status": result["alert"]["status_code"],
        "provisional": int(bool(result["provisional"])),
        "model_version": result["model_version"],
        "baseline_version": result["baseline_version"],
        "feature_schema_version": result["feature_schema_version"],
        "code_commit": result["code_commit"],
        "created_at": db.utcnow(),
    })


# ---------------------------------------------------------------------------
# training entry points
# ---------------------------------------------------------------------------

def _baseline_window(sessions: list[dict], recent: bool) -> list[dict]:
    """Select the sessions the baseline is fitted on.

    Initial fit takes the FIRST `BASELINE_WINDOW_DAYS` days; a deliberate refit
    takes the LAST. Never everything, a baseline fitted over the whole history
    quietly absorbs any gradual change and redefines it as this person's normal,
    which would make the one signal CogniDiff exists to find undetectable.
    """
    dates = sorted({s["date"] for s in sessions if s.get("date")})
    if len(dates) <= BASELINE_WINDOW_DAYS:
        return sessions

    window = dates[-BASELINE_WINDOW_DAYS:] if recent else dates[:BASELINE_WINDOW_DAYS]
    selected = [s for s in sessions if s.get("date") in set(window)]

    # If the window is too thin to fit, widen it rather than refuse, an
    # under-populated fortnight is common early on.
    if len(selected) < MIN_BASELINE_SESSIONS:
        return sessions[-MIN_BASELINE_SESSIONS * 2:] if recent else sessions[:MIN_BASELINE_SESSIONS * 2]
    return selected


def fit_baseline(user_id: str, recent: bool = False) -> dict:
    """Fit (or refit) the personal baseline and bump its version.

    `recent=False` establishes the baseline from the first two weeks.
    `recent=True` is a deliberate recalibration onto the most recent two weeks, used after a device change, an illness, or a major life change.
    """
    user = db.get_user(user_id)
    if user is None:
        raise ValueError("unknown user")

    sessions = _baseline_window(db.good_sessions(user_id), recent)
    version = int(user.get("baseline_version", 0) or 0) + 1

    baseline = PersonalBaseline(user_id, version=version).fit(sessions)
    path = baseline.save()

    db.execute(
        "UPDATE users SET baseline_version = ?, baseline_status = ?, "
        "baseline_device = ?, recalibration_started_at = NULL WHERE id = ?",
        (version, "ACTIVE", baseline.device, user_id),
    )

    return {
        "fitted": True,
        "baseline_version": version,
        "sessions_used": baseline.n_sessions,
        "window": "most recent two weeks" if recent else "first two weeks",
        "model_file": path.name,
        "summary": baseline.summary(),
    }


def fit_anomaly(user_id: str, recent: bool = False) -> dict:
    """The detector learns the same reference period as the baseline, so the two
    models are answering questions about the same notion of 'normal'."""
    sessions = _baseline_window(db.good_sessions(user_id), recent)
    detector = AnomalyDetector(user_id).fit(sessions)
    path = detector.save()
    return {
        "fitted": True,
        "sessions_used": detector.n_train,
        "contamination": detector.contamination,
        "model_file": path.name,
    }


def fit_lstm(user_id: str) -> dict:
    rows = db.query(
        "SELECT date, AVG(adjusted_score) AS s FROM cogniscores "
        "WHERE user_id = ? GROUP BY date ORDER BY date ASC",
        (user_id,),
    )
    series = [r["s"] for r in rows if r["s"] is not None]

    model = LSTMPredictor(user_id)
    info = model.train(series)
    model.save()
    return {"fitted": True, "n_days": len(series), **info,
            "evaluation": model.evaluate(series)}


def predict_tomorrow(user_id: str) -> dict:
    rows = db.query(
        "SELECT date, AVG(adjusted_score) AS s FROM cogniscores "
        "WHERE user_id = ? GROUP BY date ORDER BY date DESC LIMIT 7",
        (user_id,),
    )
    series = [r["s"] for r in reversed(rows) if r["s"] is not None]
    if not series:
        return {"predicted_score": None, "trend": "unknown", "trained": False}

    model = LSTMPredictor.load(user_id) or LSTMPredictor(user_id)
    return model.predict(series)
