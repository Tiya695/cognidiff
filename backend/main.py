"""CogniDiff API.

Route naming follows one rule with no exceptions: **no endpoint takes a user_id
for the caller's own data**. `/api/dashboard/me` resolves identity from the JWT.
The only route that names another user is the doctor report, and it is gated on
an active consent grant that is re-checked on every single request.
"""

from __future__ import annotations

import uuid
from datetime import date as _date
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import audit, database as db, rbac, scoring
from .alert_engine import AlertEngine
from .auth import (
    authenticate,
    create_access_token,
    create_user,
    get_current_user,
)
from .config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    CORS_ORIGINS,
    ENV,
    FEATURE_LABELS,
    IS_PRODUCTION,
    MAINTENANCE_MODE,
    MIN_BASELINE_SESSIONS,
    QUALITY_EXCLUDE_THRESHOLD,
    VERSIONS,
    get_git_commit,
)
from .context_tracker import ContextTracker
from .data_quality import DataQualityEngine, REASON_CODES, quality_tier
from .features import enrich_batch
from .models import (
    ConsentGrantRequest,
    ConsentRevokeRequest,
    ContextRequest,
    LoginRequest,
    RegisterRequest,
    ScoreRequest,
    SessionBatch,
    TaskScoreRequest,
)
from .ratelimit import LIMITS, enforce
from .summary_generator import generate_summary
from ml.baseline import PersonalBaseline
from ml.drift_detector import (
    ModelDriftDetector,
    STATUS_ACTIVE,
    STATUS_RECALIBRATING,
    recalibration_progress,
)

# ---------------------------------------------------------------------------
# app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="CogniDiff API",
    version="1.0.0",
    description=(
        "Privacy-preserving early cognitive change detection. "
        "CogniDiff detects deviation from an individual's own typing baseline. "
        "It does not detect, diagnose or confirm cognitive decline."
    ),
    # In production the interactive docs are a complete map of the attack
    # surface. They are a development tool, not a public page.
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
    debug=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=r"^chrome-extension://[a-p]{32}$",
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)

MAX_BODY_BYTES = 512 * 1024      # 512 KB — a legitimate batch is a few KB


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    # Reject oversized bodies before they are parsed (Attack 9).
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={"detail": "Request body too large."},
        )

    if MAINTENANCE_MODE and request.url.path.startswith("/api/") \
            and not request.url.path.startswith("/api/health"):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "CogniDiff is in maintenance mode."},
        )

    response = await call_next(request)

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Cache-Control"] = "no-store"
    if IS_PRODUCTION:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Generic message plus a request ID to the client; full traceback stays
    server-side. A stack trace in a response is a free map of the codebase."""
    request_id = uuid.uuid4().hex[:12]
    import logging
    logging.getLogger("cognidiff").exception("unhandled error [%s]", request_id)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal error occurred.",
            "request_id": request_id,
        },
    )


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

@app.get("/api/health", tags=["system"])
def health():
    return {
        "status": "ok",
        "env": ENV,
        "maintenance": MAINTENANCE_MODE,
        "versions": {**VERSIONS, "code_commit": get_git_commit()},
    }


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------

@app.post("/api/auth/register", tags=["auth"], status_code=201)
def register(body: RegisterRequest, request: Request):
    enforce(request, "login", *LIMITS["login"])
    try:
        user = create_user(body.username, body.password, body.role, body.first_name)
    except ValueError:
        # Same generic message whether the username is taken or invalid —
        # otherwise registration becomes a user-enumeration oracle.
        raise HTTPException(status_code=400, detail="Could not create that account.")

    audit.log_action(user["id"], user["role"], "REGISTER", "users",
                     audit.OUTCOME_SUCCESS, request=request)
    return {
        "user_id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "expires_in_minutes": ACCESS_TOKEN_EXPIRE_MINUTES,
    }


@app.post("/api/auth/login", tags=["auth"])
def login(body: LoginRequest, request: Request):
    enforce(request, "login", *LIMITS["login"])
    user = authenticate(body.username, body.password)

    if user is None:
        audit.log_action(None, None, "LOGIN", "auth", audit.OUTCOME_DENIED,
                         details={"username_attempted": body.username[:32]},
                         request=request)
        # One message for both "no such user" and "wrong password".
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    audit.log_action(user["id"], user["role"], "LOGIN", "auth",
                     audit.OUTCOME_SUCCESS, request=request)
    return {
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "expires_in_minutes": ACCESS_TOKEN_EXPIRE_MINUTES,
        "user_id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "first_name": user["first_name"],
    }


@app.get("/api/auth/me", tags=["auth"])
def whoami(user: dict = Depends(get_current_user)):
    return {
        "user_id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "first_name": user["first_name"],
        "baseline_status": user["baseline_status"],
        "baseline_version": user["baseline_version"],
    }


# ---------------------------------------------------------------------------
# session ingest
# ---------------------------------------------------------------------------

@app.post("/api/session", tags=["sessions"], status_code=201)
def ingest_session(
    batch: SessionBatch,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Accept one 60-second feature batch.

    The quality gate runs before anything else. Low-quality sessions are still
    stored — with `excluded = 1` and a reason code — so the exclusion rate is a
    measurable number rather than an invisible one.
    """
    enforce(request, "session", *LIMITS["session"], user=user)

    payload = batch.model_dump()
    payload.setdefault("date", _date.today().isoformat())
    if payload.get("date") is None:
        payload["date"] = _date.today().isoformat()
    if payload.get("hour") is None:
        from datetime import datetime
        payload["hour"] = datetime.now().hour

    enriched = enrich_batch(payload)
    enriched["key_categories"] = payload.get("key_categories", "")
    enriched["complete"] = payload.get("complete", True)

    gate = DataQualityEngine(baseline_device=user.get("baseline_device"))
    quality = gate.score_session(enriched)

    row = {
        "user_id": user["id"],
        "date": payload["date"],
        "hour": enriched["hour"],
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
        "created_at": db.utcnow(),
    }
    session_id = db.insert("keystroke_sessions", row)

    for code in quality.reason_codes:
        db.insert("session_exclusions", {
            "session_id": session_id,
            "user_id": user["id"],
            "date": payload["date"],
            "reason_code": code,
            "detail": REASON_CODES.get(code, code),
            "created_at": db.utcnow(),
        })

    # A device change puts the user into a recalibration window rather than
    # letting a new keyboard read as cognitive decline.
    if quality.device_changed and user.get("baseline_status") == STATUS_ACTIVE:
        db.execute(
            "UPDATE users SET baseline_status = ?, recalibration_started_at = ? "
            "WHERE id = ?",
            (STATUS_RECALIBRATING, db.utcnow(), user["id"]),
        )

    audit.log_action(user["id"], user["role"], "INGEST_SESSION",
                     f"keystroke_sessions/{session_id}", audit.OUTCOME_SUCCESS,
                     details={"quality": quality.quality_score,
                              "excluded": quality.should_exclude},
                     request=request)

    return {
        "session_id": session_id,
        "stored": True,
        **quality.as_dict(),
        "tier": quality_tier(quality.quality_score),
        "note": (
            "Session stored but excluded from cognitive scoring."
            if quality.should_exclude else
            "Session accepted for cognitive scoring."
        ),
    }


@app.get("/api/sessions/me", tags=["sessions"])
def my_sessions(user: dict = Depends(get_current_user), limit: int = 200):
    rows = db.query(
        "SELECT * FROM keystroke_sessions WHERE user_id = ? "
        "ORDER BY created_at DESC LIMIT ?",
        (user["id"], min(max(int(limit), 1), 1000)),
    )
    return {"count": len(rows), "sessions": rows}


@app.get("/api/sessions/me/today", tags=["sessions"])
def my_sessions_today(user: dict = Depends(get_current_user)):
    today = _date.today().isoformat()
    rows = db.query(
        "SELECT * FROM keystroke_sessions WHERE user_id = ? AND date = ? "
        "ORDER BY created_at ASC",
        (user["id"], today),
    )
    return {"date": today, "count": len(rows), "sessions": rows}


@app.get("/api/sessions/me/summary", tags=["sessions"])
def my_summary(user: dict = Depends(get_current_user)):
    today = _date.today().isoformat()
    row = db.query_one(
        """
        SELECT COUNT(*)                                    AS total,
               SUM(CASE WHEN excluded = 0 THEN 1 ELSE 0 END) AS accepted,
               ROUND(AVG(CASE WHEN excluded = 0 THEN wpm_estimate END), 1) AS avg_wpm,
               ROUND(AVG(quality_score), 1)                AS avg_quality
        FROM keystroke_sessions WHERE user_id = ? AND date = ?
        """,
        (user["id"], today),
    ) or {}
    slots = db.query(
        "SELECT time_slot, COUNT(*) AS n FROM keystroke_sessions "
        "WHERE user_id = ? AND date = ? AND excluded = 0 GROUP BY time_slot",
        (user["id"], today),
    )
    return {
        "date": today,
        "sessions_today": row.get("total") or 0,
        "sessions_accepted": row.get("accepted") or 0,
        "avg_wpm": row.get("avg_wpm"),
        "avg_quality_score": row.get("avg_quality"),
        "time_slots_active": [s["time_slot"] for s in slots],
    }


@app.get("/api/sessions/quality", tags=["sessions"])
def quality_report(user: dict = Depends(get_current_user)):
    """Quality tiers and the measured exclusion rate, with reasons."""
    rows = db.all_sessions(user["id"])
    tiers = {"excellent": 0, "acceptable": 0, "excluded": 0}
    for r in rows:
        tiers[quality_tier(float(r["quality_score"] or 0))] += 1

    reasons = db.query(
        "SELECT reason_code, COUNT(*) AS n FROM session_exclusions "
        "WHERE user_id = ? GROUP BY reason_code ORDER BY n DESC",
        (user["id"],),
    )
    total = len(rows)
    excluded = sum(1 for r in rows if r["excluded"])

    return {
        "total_sessions": total,
        "sessions_analysed": total - excluded,
        "sessions_excluded_quality": excluded,
        "exclusion_rate_percent": round(100 * excluded / total, 1) if total else 0.0,
        "tiers": tiers,
        "reason_breakdown": [
            {**r, "description": REASON_CODES.get(r["reason_code"], r["reason_code"])}
            for r in reasons
        ],
        "threshold": QUALITY_EXCLUDE_THRESHOLD,
    }


# ---------------------------------------------------------------------------
# model training
# ---------------------------------------------------------------------------

@app.post("/api/baseline/fit", tags=["models"])
def baseline_fit(request: Request, user: dict = Depends(get_current_user)):
    enforce(request, "fit", *LIMITS["fit"], user=user)
    try:
        result = scoring.fit_baseline(user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    audit.log_action(user["id"], user["role"], "FIT_BASELINE", "ml/baseline",
                     audit.OUTCOME_SUCCESS, request=request)
    return result


@app.post("/api/baseline/refit", tags=["models"])
def baseline_refit(request: Request, user: dict = Depends(get_current_user)):
    """Deliberate user-initiated recalibration — after illness, a new keyboard,
    or a major life change. Unlike the initial fit, this one takes the most
    recent two weeks as the new reference."""
    enforce(request, "fit", *LIMITS["fit"], user=user)
    try:
        result = scoring.fit_baseline(user["id"], recent=True)
        scoring.fit_anomaly(user["id"], recent=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    audit.log_action(user["id"], user["role"], "REFIT_BASELINE", "ml/baseline",
                     audit.OUTCOME_SUCCESS, request=request)
    return {**result, "note": "Baseline recalibrated onto your most recent two weeks."}


@app.post("/api/anomaly/fit", tags=["models"])
def anomaly_fit(request: Request, user: dict = Depends(get_current_user)):
    enforce(request, "fit", *LIMITS["fit"], user=user)
    try:
        return scoring.fit_anomaly(user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/lstm/fit", tags=["models"])
def lstm_fit(request: Request, user: dict = Depends(get_current_user)):
    enforce(request, "fit", *LIMITS["fit"], user=user)
    try:
        return scoring.fit_lstm(user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/lstm/predict", tags=["models"])
def lstm_predict(user: dict = Depends(get_current_user)):
    return scoring.predict_tomorrow(user["id"])


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

@app.post("/api/score", tags=["scoring"])
def score(body: ScoreRequest, request: Request, user: dict = Depends(get_current_user)):
    """Compute and persist today's CogniScore.

    `body` carries no score fields and cannot: ScoreRequest forbids extras, so
    a client sending `raw_score=100` gets 422 rather than a compliment.
    """
    enforce(request, "score", *LIMITS["score"], user=user)
    try:
        result = scoring.score_user(user["id"], persist=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    audit.log_action(user["id"], user["role"], "COMPUTE_SCORE", "cogniscores",
                     audit.OUTCOME_SUCCESS, request=request)
    return result


@app.get("/api/alert/me", tags=["scoring"])
def my_alert(user: dict = Depends(get_current_user)):
    rows = db.query(
        "SELECT adjusted_score, is_anomaly, alert_status, confidence_band "
        "FROM cogniscores WHERE user_id = ? ORDER BY id DESC LIMIT 7",
        (user["id"],),
    )
    if not rows:
        return AlertEngine().evaluate(
            user["id"], [], [], baseline_status="INSUFFICIENT_DATA"
        ).as_dict()

    rows = list(reversed(rows))
    return AlertEngine().evaluate(
        user_id=user["id"],
        recent_scores=[r["adjusted_score"] for r in rows],
        recent_anomalies=[bool(r["is_anomaly"]) for r in rows],
        trend_30d=scoring._trend_direction(user["id"]),
        baseline_status=user.get("baseline_status", "ACTIVE"),
        confidence_band=rows[-1]["confidence_band"],
    ).as_dict()


@app.get("/api/summary/me", tags=["scoring"])
def my_summary_text(request: Request, user: dict = Depends(get_current_user)):
    """Score + explanation + Claude-generated plain-language summary."""
    enforce(request, "summary", *LIMITS["summary"], user=user)

    result = scoring.score_user(user["id"], persist=False)
    if result["status"] != "OK":
        return {**result, "summary": None}

    days = db.query_one(
        "SELECT COUNT(DISTINCT date) AS n FROM cogniscores "
        "WHERE user_id = ? AND adjusted_score < 70 "
        "AND date >= date('now', 'localtime', '-30 day')",
        (user["id"],),
    ) or {}

    summary = generate_summary(
        cogni_score=result["cogni_score"],
        top_3_changes=result["top_3_changes"],
        trend_direction=scoring._trend_direction(user["id"]),
        user_first_name=user.get("first_name"),
        confidence_band=result["confidence_band"],
        days_persisted=int(days.get("n") or 0),
    )

    audit.log_action(user["id"], user["role"], "GENERATE_SUMMARY", "summary",
                     audit.OUTCOME_SUCCESS,
                     details={"source": summary["source"]}, request=request)

    return {
        "cogni_score": result["cogni_score"],
        "confidence": result["confidence"],
        "confidence_band": result["confidence_band"],
        "top_3_changes": result["top_3_changes"],
        "alert": result["alert"],
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# dashboard
# ---------------------------------------------------------------------------

@app.get("/api/dashboard/me", tags=["dashboard"])
def dashboard(request: Request, user: dict = Depends(get_current_user)):
    """Everything the dashboard needs, in one call."""
    user_id = user["id"]
    result = scoring.score_user(user_id, persist=False)

    quality = quality_report(user)
    drift = _drift_for(user)

    payload = {
        "user": {
            "first_name": user.get("first_name"),
            "username": user["username"],
            "baseline_status": user.get("baseline_status"),
            "baseline_version": user.get("baseline_version"),
        },
        "status": result["status"],
        "message": result.get("message"),
        "current_score": result.get("cogni_score"),
        "raw_score": result.get("raw_score"),
        "adjusted_score": result.get("adjusted_score"),
        "task_score": result.get("task_score"),
        "composite_weighting": result.get("composite_weighting"),
        "confidence": result.get("confidence"),
        "confidence_band": result.get("confidence_band"),
        "confidence_breakdown": result.get("confidence_breakdown"),
        "provisional": result.get("provisional", True),
        "deviation_percent": result.get("deviation_percent"),
        "quality_score": result.get("quality_score"),
        "alert_status": result.get("alert"),
        "top_3_changes": result.get("top_3_changes", []),
        "explanation_method": result.get("explanation_method"),
        "per_feature": result.get("per_feature", {}),
        "worst_feature": result.get("top_deviating_feature"),
        "dual_confirmation": result.get("dual_confirmation"),
        "context": result.get("context"),
        "trend_7d": db.daily_scores(user_id, 7),
        "trend_30d": db.daily_scores(user_id, 30),
        "trend_90d": db.daily_scores(user_id, 90),
        "trend_direction": scoring._trend_direction(user_id),
        "lstm_prediction_tomorrow": scoring.predict_tomorrow(user_id),
        "time_slot_breakdown": db.query(
            "SELECT time_slot, COUNT(*) AS sessions, "
            "ROUND(AVG(wpm_estimate),1) AS avg_wpm, "
            "ROUND(AVG(quality_score),1) AS avg_quality "
            "FROM keystroke_sessions WHERE user_id = ? AND excluded = 0 "
            "GROUP BY time_slot",
            (user_id,),
        ),
        "total_sessions": quality["total_sessions"],
        "sessions_analysed": quality["sessions_analysed"],
        "sessions_excluded_quality": quality["sessions_excluded_quality"],
        "exclusion_rate_percent": quality["exclusion_rate_percent"],
        "exclusion_reasons": quality["reason_breakdown"],
        "drift": drift,
        "feature_labels": FEATURE_LABELS,
        "baseline_required": MIN_BASELINE_SESSIONS,
        "versions": {**VERSIONS, "code_commit": get_git_commit()},
    }

    audit.log_action(user_id, user["role"], "VIEW_DASHBOARD", "dashboard",
                     audit.OUTCOME_SUCCESS, request=request)
    return payload


def _drift_for(user: dict) -> dict:
    baseline = PersonalBaseline.load(user["id"])
    if baseline is None or not baseline.is_fitted:
        return {"drift_severity": "unknown", "drifted_features": [],
                "classification": "STABLE",
                "recommended_action": "monitor"}
    sessions = db.good_sessions(user["id"])
    try:
        detector = ModelDriftDetector(baseline)
        drift = detector.check_drift(sessions)
        drift.update(detector.classify_drift(sessions))
    except Exception:
        return {"drift_severity": "unknown", "drifted_features": [],
                "classification": "STABLE", "recommended_action": "monitor"}

    if user.get("baseline_status") == STATUS_RECALIBRATING:
        since = db.query_one(
            "SELECT COUNT(*) AS n FROM keystroke_sessions "
            "WHERE user_id = ? AND excluded = 0 AND created_at >= "
            "COALESCE((SELECT recalibration_started_at FROM users WHERE id = ?), '')",
            (user["id"], user["id"]),
        ) or {}
        drift["recalibration"] = recalibration_progress(int(since.get("n") or 0))
    return drift


@app.get("/api/drift/me", tags=["dashboard"])
def my_drift(user: dict = Depends(get_current_user)):
    return _drift_for(user)


# ---------------------------------------------------------------------------
# mini-tasks
# ---------------------------------------------------------------------------

@app.post("/api/task-score", tags=["tasks"], status_code=201)
def submit_task_score(
    body: TaskScoreRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Store one round of the four cognitive mini-tasks.

    The composite is computed here, server-side, from the four raw measurements.
    The client cannot send a composite — the field does not exist on the model.
    """
    today = _date.today().isoformat()
    parts: list[float] = []

    if body.word_recall is not None:
        parts.append(min(100.0, body.word_recall / 5.0 * 100.0))
    if body.reaction_time_ms is not None:
        # 250 ms → 100, 800 ms → 0. Linear between.
        parts.append(max(0.0, min(100.0, (800.0 - body.reaction_time_ms) / 5.5)))
    if body.pattern_memory is not None:
        parts.append(min(100.0, body.pattern_memory / 5.0 * 100.0))
    if body.letter_scramble_ms is not None:
        # 3 s → 100, 20 s → 0.
        parts.append(max(0.0, min(100.0, (20_000.0 - body.letter_scramble_ms) / 170.0)))

    if not parts:
        raise HTTPException(status_code=422, detail="No task results supplied.")

    composite = round(sum(parts) / len(parts), 1)

    row_id = db.insert("task_results", {
        "user_id": user["id"],
        "date": today,
        "word_recall": body.word_recall,
        "reaction_time_ms": body.reaction_time_ms,
        "pattern_memory": body.pattern_memory,
        "letter_scramble_ms": body.letter_scramble_ms,
        "composite_task_score": composite,
        "created_at": db.utcnow(),
    })

    audit.log_action(user["id"], user["role"], "SUBMIT_TASKS",
                     f"task_results/{row_id}", audit.OUTCOME_SUCCESS,
                     request=request)
    return {
        "id": row_id,
        "date": today,
        "composite_task_score": composite,
        "tasks_completed": len(parts),
        "note": "Today's CogniScore will now blend keystroke and task evidence.",
    }


@app.get("/api/task-score/me", tags=["tasks"])
def my_task_scores(user: dict = Depends(get_current_user), limit: int = 30):
    return {"results": db.query(
        "SELECT * FROM task_results WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user["id"], min(int(limit), 200)),
    )}


# ---------------------------------------------------------------------------
# context
# ---------------------------------------------------------------------------

@app.post("/api/context", tags=["context"])
def set_context(
    body: ContextRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    today = _date.today().isoformat()
    saved = ContextTracker.save(
        user["id"], today,
        sleep_quality=body.sleep_quality,
        stress_level=body.stress_level,
        device_changed=body.device_changed,
        feeling_unwell=body.feeling_unwell,
    )

    if body.device_changed:
        db.execute(
            "UPDATE users SET baseline_status = ?, recalibration_started_at = ? "
            "WHERE id = ? AND baseline_status = ?",
            (STATUS_RECALIBRATING, db.utcnow(), user["id"], STATUS_ACTIVE),
        )

    audit.log_action(user["id"], user["role"], "SET_CONTEXT", "daily_context",
                     audit.OUTCOME_SUCCESS, request=request)
    return {"saved": True, "date": today, "context": saved}


@app.get("/api/context/me", tags=["context"])
def get_context(user: dict = Depends(get_current_user)):
    today = _date.today().isoformat()
    return {"date": today, "context": ContextTracker.get(user["id"], today)}


# ---------------------------------------------------------------------------
# consent
# ---------------------------------------------------------------------------

@app.post("/api/consent/grant", tags=["consent"])
def consent_grant(
    body: ConsentGrantRequest,
    request: Request,
    user: dict = Depends(rbac.require_user_role),
):
    result = rbac.grant_consent(user["id"], body.doctor_username)
    audit.log_action(user["id"], user["role"], "GRANT_CONSENT",
                     f"consent/{body.doctor_username}", audit.OUTCOME_SUCCESS,
                     request=request)
    return result


@app.post("/api/consent/revoke", tags=["consent"])
def consent_revoke(
    body: ConsentRevokeRequest,
    request: Request,
    user: dict = Depends(rbac.require_user_role),
):
    result = rbac.revoke_consent(user["id"], body.doctor_id)
    audit.log_action(user["id"], user["role"], "REVOKE_CONSENT",
                     f"consent/{body.doctor_id}", audit.OUTCOME_SUCCESS,
                     request=request)
    return result


@app.get("/api/consent/my-grants", tags=["consent"])
def my_grants(user: dict = Depends(get_current_user)):
    return {"grants": rbac.list_grants(user["id"])}


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------

@app.get("/api/doctor/patients", tags=["doctor"])
def doctor_patients(
    request: Request,
    doctor: dict = Depends(rbac.require_doctor_role),
):
    patients = rbac.list_patients(doctor["id"])
    audit.log_action(doctor["id"], doctor["role"], "LIST_PATIENTS", "doctor",
                     audit.OUTCOME_SUCCESS, request=request)
    return {"count": len(patients), "patients": patients}


DISCLAIMER = (
    "CogniDiff is a monitoring and screening tool. It does not diagnose any "
    "medical condition. CogniDiff detects deviation from an individual's own "
    "typing baseline; it does not detect, diagnose or confirm cognitive "
    "decline, and no clinical sensitivity or specificity is claimed because no "
    "clinically labelled data was used. These results should be interpreted by "
    "a qualified healthcare professional."
)


def _doctor_report(target_id: str) -> dict:
    baseline = PersonalBaseline.load(target_id)
    target = db.get_user(target_id)

    current = db.query_one(
        "SELECT ROUND(AVG(adjusted_score),1) AS avg_score, COUNT(*) AS n "
        "FROM cogniscores WHERE user_id = ? "
        "AND date >= date('now','localtime','-14 day')",
        (target_id,),
    ) or {}
    earlier = db.query_one(
        "SELECT ROUND(AVG(adjusted_score),1) AS avg_score "
        "FROM cogniscores WHERE user_id = ? "
        "AND date <  date('now','localtime','-14 day') "
        "AND date >= date('now','localtime','-45 day')",
        (target_id,),
    ) or {}

    current_avg = current.get("avg_score")
    earlier_avg = earlier.get("avg_score")
    change_pct = (
        round((current_avg - earlier_avg) / earlier_avg * 100, 1)
        if current_avg is not None and earlier_avg else None
    )

    latest = db.query_one(
        "SELECT * FROM cogniscores WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (target_id,),
    ) or {}

    quality = db.query_one(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN excluded = 1 THEN 1 ELSE 0 END) AS excluded "
        "FROM keystroke_sessions WHERE user_id = ?",
        (target_id,),
    ) or {}

    top_features = db.query(
        "SELECT top_deviating_feature AS feature, COUNT(*) AS days, "
        "ROUND(AVG(deviation_percent),1) AS avg_deviation "
        "FROM cogniscores WHERE user_id = ? "
        "AND date >= date('now','localtime','-30 day') "
        "AND top_deviating_feature IS NOT NULL "
        "GROUP BY top_deviating_feature ORDER BY days DESC LIMIT 5",
        (target_id,),
    )
    for f in top_features:
        f["label"] = FEATURE_LABELS.get(f["feature"], f["feature"])

    grants = rbac.list_grants(target_id)

    return {
        "patient": {
            "first_name": target.get("first_name") if target else None,
            "username": target.get("username") if target else None,
            "user_id": target_id,
            "baseline_status": target.get("baseline_status") if target else None,
        },
        "baseline_period": {
            "start": baseline.period[0] if baseline else None,
            "end": baseline.period[1] if baseline else None,
            "sessions": baseline.n_sessions if baseline else 0,
            "version": baseline.version if baseline else None,
        },
        "current_avg_score": current_avg,
        "previous_avg_score": earlier_avg,
        "score_change_percent": change_pct,
        "trend_direction": scoring._trend_direction(target_id),
        "top_deviating_features": top_features,
        "alert_status": latest.get("alert_status", "INSUFFICIENT_DATA"),
        "confidence_level": latest.get("confidence"),
        "confidence_band": latest.get("confidence_band", "LOW"),
        "provisional": bool(latest.get("provisional", 1)),
        "sessions_analyzed": (quality.get("total") or 0) - (quality.get("excluded") or 0),
        "sessions_excluded_quality": quality.get("excluded") or 0,
        "trend_90d": db.daily_scores(target_id, 90),
        "consent_record": [
            {"doctor": g["doctor_username"], "granted_at": g["granted_at"],
             "revoked_at": g["revoked_at"], "active": g["active"]}
            for g in grants
        ],
        "versions": {
            "model_version": latest.get("model_version"),
            "baseline_version": latest.get("baseline_version"),
            "feature_schema_version": latest.get("feature_schema_version"),
            "code_commit": latest.get("code_commit"),
        },
        "generated_at": db.utcnow(),
        "disclaimer": DISCLAIMER,
    }


@app.get("/api/doctor-report/me", tags=["doctor"])
def my_doctor_report(request: Request, user: dict = Depends(get_current_user)):
    audit.log_action(user["id"], user["role"], "VIEW_DOCTOR_REPORT",
                     "doctor_report", audit.OUTCOME_SUCCESS, request=request)
    return _doctor_report(user["id"])


@app.get("/api/doctor-report/{target_user_id}", tags=["doctor"])
def doctor_report_for(
    target_user_id: str,
    request: Request,
    actor: dict = Depends(get_current_user),
):
    """The only endpoint that names another user — and it is gated on a consent
    grant re-checked on every call, with the denial recorded either way."""
    try:
        rbac.require_self_or_consenting_doctor(target_user_id, actor)
    except HTTPException:
        audit.log_action(actor["id"], actor["role"], "VIEW_DOCTOR_REPORT",
                         f"doctor_report/{target_user_id}", audit.OUTCOME_DENIED,
                         user_id=target_user_id, request=request)
        raise

    audit.log_action(actor["id"], actor["role"], "VIEW_DOCTOR_REPORT",
                     f"doctor_report/{target_user_id}", audit.OUTCOME_SUCCESS,
                     user_id=target_user_id, request=request)
    return _doctor_report(target_user_id)


# ---------------------------------------------------------------------------
# audit log
# ---------------------------------------------------------------------------

@app.get("/api/audit-log/me", tags=["audit"])
def my_audit_log(user: dict = Depends(get_current_user), limit: int = 50):
    return {"entries": audit.recent_for_user(user["id"], limit)}


# ---------------------------------------------------------------------------
# research endpoints
# ---------------------------------------------------------------------------

@app.get("/api/feature-importance", tags=["research"])
def feature_importance(user: dict = Depends(get_current_user)):
    from ml.xgb_model import XGBCogniClassifier
    model = XGBCogniClassifier.load(user["id"])
    if model is None or not model.is_fitted:
        return {
            "available": False,
            "note": "Exploratory model not trained yet. POST /api/anomaly/fit first.",
        }
    return {
        "available": True,
        "importance": model.feature_importance(),
        "backend": model.backend,
        "warning": (
            "Trained on IsolationForest pseudo-labels, not clinical ground "
            "truth. Exploratory only — no clinical validation is claimed."
        ),
    }


@app.get("/api/ablation/me", tags=["research"])
def ablation(user: dict = Depends(get_current_user)):
    from ml.ablation import run_ablation
    sessions = db.good_sessions(user["id"])
    if len(sessions) < 15:
        return {"available": False,
                "note": f"Need at least 15 quality sessions; have {len(sessions)}."}
    return {"available": True, **run_ablation(sessions)}


@app.get("/api/federated/status", tags=["research"])
def federated_status():
    rows = db.query(
        "SELECT * FROM federated_rounds ORDER BY id DESC LIMIT 10", ()
    )
    return {
        "federated_mode": "simulation",
        "rounds_completed": len(rows),
        "last_round_accuracy": rows[0]["accuracy"] if rows else None,
        "rounds": rows,
        "limitation": (
            "Federated learning reduces the need to centrally collect raw "
            "keystroke features, because training can occur locally and only "
            "model updates are aggregated. It is not an automatic privacy "
            "guarantee: model updates can leak information about the data they "
            "were trained on (gradient inversion, membership inference). "
            "Secure aggregation and differential privacy are future work."
        ),
    }


# ---------------------------------------------------------------------------
# data control
# ---------------------------------------------------------------------------

@app.get("/api/export/me", tags=["privacy"])
def export_my_data(request: Request, user: dict = Depends(get_current_user)):
    """Everything CogniDiff holds about the caller. Portability is part of
    control — a user who cannot see their data cannot judge our claims."""
    audit.log_action(user["id"], user["role"], "EXPORT_DATA", "export",
                     audit.OUTCOME_SUCCESS, request=request)
    return {
        "exported_at": db.utcnow(),
        "note": "No typed text exists in this export because none was ever stored.",
        "sessions": db.all_sessions(user["id"]),
        "scores": db.query("SELECT * FROM cogniscores WHERE user_id = ?", (user["id"],)),
        "tasks": db.query("SELECT * FROM task_results WHERE user_id = ?", (user["id"],)),
        "context": db.query("SELECT * FROM daily_context WHERE user_id = ?", (user["id"],)),
        "consent_grants": rbac.list_grants(user["id"]),
    }


@app.delete("/api/user/me", tags=["privacy"])
def delete_me(request: Request, user: dict = Depends(get_current_user)):
    """Erase every row belonging to the caller, across every table."""
    removed = db.delete_user_data(user["id"])

    from pathlib import Path
    from .config import MODEL_DIR
    for pattern in (f"baseline_{user['id']}*.pkl", f"anomaly_{user['id']}.pkl",
                    f"lstm_{user['id']}.pkl", f"xgb_{user['id']}.pkl"):
        for path in Path(MODEL_DIR).glob(pattern):
            path.unlink(missing_ok=True)

    db.execute(
        "UPDATE users SET baseline_status = ?, baseline_version = 0, "
        "baseline_device = NULL, token_version = token_version + 1 WHERE id = ?",
        ("INSUFFICIENT_DATA", user["id"]),
    )

    audit.log_action(user["id"], user["role"], "DELETE_ALL_DATA", "user",
                     audit.OUTCOME_SUCCESS,
                     details={"rows_removed": sum(removed.values())},
                     request=request)

    return {
        "deleted": True,
        "rows_removed": removed,
        "models_deleted": True,
        "message": (
            "All your data has been deleted and your models removed. Your "
            "session has been invalidated — please sign in again."
        ),
    }
