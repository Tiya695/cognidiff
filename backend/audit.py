"""Audit logging.

CogniDiff does not only protect health data, it records every access to it.
A user can open their dashboard and see exactly who looked at their cognitive
information and when, including their own logins and every doctor view.

What is never logged: keystroke data, feature values, scores, or any health
content. The log answers *who did what to which resource and did it succeed*, nothing about what the data said. An audit trail that leaks the thing it is
guarding is worse than none.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Request

from . import database as db

OUTCOME_SUCCESS = "SUCCESS"
OUTCOME_DENIED = "DENIED"

#: Field names that must never reach the details column, even by accident.
_FORBIDDEN_DETAIL_KEYS = {
    "raw_text", "key_categories", "offsets_ms", "intervals_ms", "password",
    "token", "cogni_score", "raw_score", "adjusted_score", "wpm_estimate",
    "avg_iki_ms", "per_feature",
}


def client_ip(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    # X-Forwarded-For is client-controlled and is recorded as a hint only; it is
    # never used for any authorisation decision.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return request.client.host if request.client else None


def _sanitise(details: Optional[str | dict]) -> Optional[str]:
    if details is None:
        return None
    if isinstance(details, dict):
        safe = {k: v for k, v in details.items() if k not in _FORBIDDEN_DETAIL_KEYS}
        return "; ".join(f"{k}={v}" for k, v in safe.items())[:500]
    return str(details)[:500]


def log_action(
    actor_id: Optional[str],
    actor_role: Optional[str],
    action: str,
    resource: str,
    outcome: str,
    details: Optional[str | dict] = None,
    user_id: Optional[str] = None,
    request: Optional[Request] = None,
) -> int:
    """Insert one audit row. Never raises, a logging failure must not take
    down the request it was recording."""
    try:
        return db.insert("security_audit_log", {
            "timestamp": db.utcnow(),
            "user_id": user_id or actor_id,
            "actor_id": actor_id,
            "actor_role": actor_role,
            "action": action,
            "resource": resource,
            "outcome": outcome,
            "ip_address": client_ip(request),
            "details": _sanitise(details),
        })
    except Exception:
        return 0


def recent_for_user(user_id: str, limit: int = 50) -> list[dict]:
    """The last N actions taken on this user's data, by anyone."""
    return db.query(
        """
        SELECT a.id, a.timestamp, a.action, a.resource, a.outcome,
               a.actor_role, a.details,
               CASE WHEN a.actor_id = ? THEN 'you'
                    ELSE COALESCE(u.username, 'unknown') END AS actor
        FROM security_audit_log a
        LEFT JOIN users u ON u.id = a.actor_id
        WHERE a.user_id = ?
        ORDER BY a.id DESC
        LIMIT ?
        """,
        (user_id, user_id, min(int(limit), 200)),
    )
