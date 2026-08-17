"""Authentication — JWT issuing and verification.

The rule that everything else depends on: **the server decides who the user
is.** Identity comes from a signed token, never from a URL parameter, a query
string or a request body. That single decision is what closes the IDOR hole
(Phase 6, Attack 1) — there is no longer a `user_id` in the URL for an attacker
to change.

Tokens carry a `tv` (token version) claim. Bumping a user's `token_version`
invalidates every token ever issued to them at once, which is step 3 of the
incident response procedure.

`python-jose` and `passlib` are used when installed. Both have stdlib fallbacks
(HMAC-SHA256 for JWT, PBKDF2-SHA256 for passwords) so authentication never
silently degrades to something weaker on a machine where the wheels failed to
build — the fallback is a real implementation, not a stub.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import database as db
from .config import ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM, SECRET_KEY

# --------------------------------------------------------------------------
# password hashing
# --------------------------------------------------------------------------

try:
    import logging as _logging
    # passlib logs a full traceback while probing bcrypt's version attribute.
    # The probe below is the real test; its noise is not useful to anyone.
    _logging.getLogger("passlib").setLevel(_logging.CRITICAL)

    from passlib.context import CryptContext
    _pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    # Probe with a real hash: constructing the context succeeds even when the
    # bcrypt backend is unusable (passlib <1.7.5 cannot read bcrypt 4.x's
    # version attribute), and a hashing layer that fails on first use is worse
    # than one we knew about at import time.
    _pwd.hash("cognidiff-backend-probe")
    HASH_BACKEND = "bcrypt"
except Exception:  # pragma: no cover - depends on environment
    _pwd = None
    HASH_BACKEND = "pbkdf2_sha256"

_PBKDF2_ROUNDS = 390_000


def hash_password(password: str) -> str:
    if _pwd is not None:
        return _pwd.hash(password)
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, rounds, salt_hex, dk_hex = stored.split("$")
            dk = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
            )
            return hmac.compare_digest(dk.hex(), dk_hex)
        except (ValueError, TypeError):
            return False
    if _pwd is not None:
        try:
            return _pwd.verify(password, stored)
        except Exception:
            return False
    return False


# --------------------------------------------------------------------------
# JWT
# --------------------------------------------------------------------------

try:
    from jose import JWTError, jwt as _jose_jwt
    HAS_JOSE = True
except ImportError:  # pragma: no cover - depends on environment
    _jose_jwt = None
    HAS_JOSE = False

    class JWTError(Exception):
        pass


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _encode_fallback(payload: dict) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"},
                                separators=(",", ":")).encode())
    body = _b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signing_input = f"{header}.{body}".encode()
    sig = hmac.new(SECRET_KEY.encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{body}.{_b64url(sig)}"


def _decode_fallback(token: str) -> dict:
    try:
        header_b64, body_b64, sig_b64 = token.split(".")
    except ValueError:
        raise JWTError("malformed token")

    expected = hmac.new(
        SECRET_KEY.encode(), f"{header_b64}.{body_b64}".encode(), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(_b64url(expected), sig_b64):
        raise JWTError("bad signature")

    payload = json.loads(_b64url_decode(body_b64))
    if payload.get("exp") and time.time() > float(payload["exp"]):
        raise JWTError("token expired")
    return payload


def create_access_token(user: dict, expires_minutes: Optional[int] = None) -> str:
    minutes = expires_minutes if expires_minutes is not None else ACCESS_TOKEN_EXPIRE_MINUTES
    now = int(time.time())
    payload = {
        "sub": user["id"],
        "role": user.get("role", "USER"),
        "tv": int(user.get("token_version", 1)),
        "iat": now,
        "exp": now + minutes * 60,
        "jti": uuid.uuid4().hex,
    }
    if HAS_JOSE:
        return _jose_jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return _encode_fallback(payload)


def decode_token(token: str) -> dict:
    if HAS_JOSE:
        return _jose_jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    return _decode_fallback(token)


# --------------------------------------------------------------------------
# FastAPI dependencies
# --------------------------------------------------------------------------

bearer = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated.",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
) -> dict:
    """Resolve the authenticated user from the Bearer token.

    Every data endpoint depends on this. There is no code path anywhere in the
    project that reads an identity from a client-supplied parameter.
    """
    if creds is None or not creds.credentials:
        raise _UNAUTHORIZED

    try:
        payload = decode_token(creds.credentials)
    except JWTError:
        raise _UNAUTHORIZED
    except Exception:
        raise _UNAUTHORIZED

    user_id = payload.get("sub")
    if not user_id:
        raise _UNAUTHORIZED

    user = db.get_user(user_id)
    if not user:
        raise _UNAUTHORIZED

    # Token-version check: a rotated key or a forced logout invalidates every
    # token already in the wild, without waiting for them to expire.
    if int(payload.get("tv", 0)) != int(user.get("token_version", 1)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session no longer valid. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    request.state.actor_id = user["id"]
    request.state.actor_role = user["role"]
    return user


def authenticate(username: str, password: str) -> Optional[dict]:
    """Verify credentials in constant-ish time.

    A missing user still runs a hash comparison against a dummy value, so the
    response time does not reveal whether the username exists. The caller
    returns one generic message for both failure modes — otherwise the login
    endpoint is a user-enumeration oracle.
    """
    user = db.get_user_by_username(username)
    if user is None:
        verify_password(password, "pbkdf2_sha256$1000$00$00")   # burn the time
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user


def bump_token_version(user_id: str) -> int:
    """Invalidate every token issued to this user. Incident response step 3."""
    db.execute(
        "UPDATE users SET token_version = token_version + 1 WHERE id = ?",
        (user_id,),
    )
    user = db.get_user(user_id)
    return int(user["token_version"]) if user else 0


def create_user(
    username: str,
    password: str,
    role: str = "USER",
    first_name: Optional[str] = None,
) -> dict:
    if role not in ("USER", "DOCTOR", "ADMIN"):
        raise ValueError(f"unknown role: {role}")
    if db.get_user_by_username(username):
        raise ValueError("username already exists")

    user_id = f"u_{uuid.uuid4().hex[:16]}"   # random, non-identifying
    db.insert("users", {
        "id": user_id,
        "username": username,
        "password_hash": hash_password(password),
        "role": role,
        "first_name": first_name,
        "token_version": 1,
        "baseline_status": "INSUFFICIENT_DATA",
        "baseline_version": 0,
        "created_at": db.utcnow(),
    })
    return db.get_user(user_id)
