"""Role-based access control and consent.

Three roles, and one deliberate design decision inside them:

  USER    — can access their own data, and only their own.
  DOCTOR  — can access the data of users who have *explicitly* granted them
            access, and only while that grant is active.
  ADMIN   — system management. **No access to health data by default.**

That last line is the one worth defending. Most systems make the admin role a
superset of everything, which means the operator of a health tool can read every
patient's data with no consent and no clinical reason. CogniDiff does not: an
admin can manage accounts and read the audit log, but the health endpoints
refuse them exactly as they refuse a stranger. Internal misuse is a real threat
model, not a hypothetical one.

Consent is checked per request, never cached. Revocation therefore takes effect
on the very next call — a grace period would be a real vulnerability
(Phase 6, Attack 11).
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, status

from . import database as db
from .auth import get_current_user

ROLE_USER = "USER"
ROLE_DOCTOR = "DOCTOR"
ROLE_ADMIN = "ADMIN"


def _forbid(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


# --------------------------------------------------------------------------
# role dependencies
# --------------------------------------------------------------------------

def require_user_role(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != ROLE_USER:
        raise _forbid("This endpoint serves personal data and is for user accounts.")
    return user


def require_doctor_role(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != ROLE_DOCTOR:
        raise _forbid("Doctor role required.")
    return user


def require_admin_role(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != ROLE_ADMIN:
        raise _forbid("Admin role required.")
    return user


def require_self_or_consenting_doctor(target_user_id: str, actor: dict) -> dict:
    """Authorise access to `target_user_id`'s health data.

    Returns the target user record, or raises 403. The three branches are the
    whole access-control policy for health data:

      * the user themselves — always allowed;
      * a doctor holding an active consent grant — allowed while it lasts;
      * anyone else, including ADMIN — refused.
    """
    if actor["id"] == target_user_id:
        return actor

    if actor["role"] == ROLE_DOCTOR:
        if not db.has_active_consent(target_user_id, actor["id"]):
            raise _forbid(
                "No active consent grant from this user. Ask them to grant "
                "access from their dashboard."
            )
        target = db.get_user(target_user_id)
        if target is None:
            # Same message as the no-consent case on purpose: a doctor must not
            # be able to probe which user IDs exist by reading the error.
            raise _forbid(
                "No active consent grant from this user. Ask them to grant "
                "access from their dashboard."
            )
        return target

    raise _forbid("You do not have access to this user's data.")


# --------------------------------------------------------------------------
# consent lifecycle
# --------------------------------------------------------------------------

def grant_consent(user_id: str, doctor_username: str) -> dict:
    doctor = db.get_user_by_username(doctor_username)
    if doctor is None or doctor["role"] != ROLE_DOCTOR:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No doctor account found with that username.",
        )
    if doctor["id"] == user_id:
        raise HTTPException(status_code=400, detail="You cannot grant access to yourself.")

    if db.has_active_consent(user_id, doctor["id"]):
        return {"granted": True, "already_active": True,
                "doctor_username": doctor_username}

    db.insert("consent_grants", {
        "user_id": user_id,
        "granted_to": doctor["id"],
        "granted_at": db.utcnow(),
        "revoked_at": None,
        "active": 1,
    })
    return {"granted": True, "already_active": False,
            "doctor_username": doctor_username, "doctor_id": doctor["id"]}


def revoke_consent(user_id: str, doctor_id: str) -> dict:
    changed = db.execute(
        "UPDATE consent_grants SET active = 0, revoked_at = ? "
        "WHERE user_id = ? AND granted_to = ? AND active = 1",
        (db.utcnow(), user_id, doctor_id),
    )
    # Effective immediately: the next request from that doctor re-reads
    # consent_grants and gets 403. Nothing is cached, so there is no window.
    return {"revoked": True, "grants_closed": changed if changed else 0}


def list_grants(user_id: str) -> list[dict]:
    rows = db.query(
        """
        SELECT g.id, g.granted_to, g.granted_at, g.revoked_at, g.active,
               u.username AS doctor_username, u.first_name AS doctor_name
        FROM consent_grants g
        JOIN users u ON u.id = g.granted_to
        WHERE g.user_id = ?
        ORDER BY g.granted_at DESC
        """,
        (user_id,),
    )
    for r in rows:
        r["active"] = bool(r["active"])
    return rows


def list_patients(doctor_id: str) -> list[dict]:
    """Users who have granted this doctor active access."""
    return db.query(
        """
        SELECT u.id AS user_id, u.username, u.first_name,
               g.granted_at, u.baseline_status
        FROM consent_grants g
        JOIN users u ON u.id = g.user_id
        WHERE g.granted_to = ? AND g.active = 1 AND g.revoked_at IS NULL
        ORDER BY g.granted_at DESC
        """,
        (doctor_id,),
    )
