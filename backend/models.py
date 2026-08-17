"""Request models.

Every model here sets ``extra="forbid"``. That single line is what makes
Attack 6 (typed-text injection) and Attack 12 (score manipulation) return 422
instead of quietly succeeding: a client that sends `raw_text`, `cogni_score`,
`adjusted_score` or `anomaly` is rejected outright rather than having the field
silently ignored — because a silently ignored field is a field someone will
eventually find a way to make count.

Ranges are not decoration either. `total_keystrokes` cannot exceed 10,000 in a
60-second window because no human types 166 keys per second; a payload claiming
otherwise is either broken or hostile, and both deserve a 422.
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

STRICT = ConfigDict(extra="forbid")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CATEGORY_RE = re.compile(r"^[ldsbp]*$")


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    model_config = STRICT
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)


class RegisterRequest(BaseModel):
    model_config = STRICT
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    first_name: Optional[str] = Field(default=None, max_length=64)
    role: str = Field(default="USER")

    @field_validator("username")
    @classmethod
    def _username_charset(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", v):
            raise ValueError("Username may contain letters, digits, dot, underscore and hyphen only.")
        return v.lower()

    @field_validator("role")
    @classmethod
    def _role_allowed(cls, v: str) -> str:
        v = v.upper()
        if v not in ("USER", "DOCTOR"):
            # ADMIN is never self-registerable. It is provisioned out of band.
            raise ValueError("Role must be USER or DOCTOR.")
        return v


# ---------------------------------------------------------------------------
# session ingest
# ---------------------------------------------------------------------------

class SessionBatch(BaseModel):
    """One 60-second feature batch from the extension.

    Note what is absent and cannot be added: there is no field for typed text,
    and no field for a score. The client supplies behaviour; the server derives
    meaning.
    """
    model_config = STRICT

    wpm_estimate: float = Field(ge=0, le=300)
    avg_inter_key_interval_ms: float = Field(ge=0, le=30_000)
    avg_hold_duration_ms: float = Field(ge=0, le=5_000)
    backspace_count: int = Field(ge=0, le=10_000)
    total_keystrokes: int = Field(ge=0, le=10_000)
    pause_count: int = Field(ge=0, le=10_000)
    session_minute: int = Field(default=0, ge=0, le=10_000)

    long_pause_count: Optional[int] = Field(default=None, ge=0, le=10_000)
    duration_ms: int = Field(default=0, ge=0, le=600_000)

    key_categories: str = Field(default="", max_length=20_000)
    offsets_ms: list[float] = Field(default_factory=list, max_length=10_000)
    intervals_ms: list[float] = Field(default_factory=list, max_length=10_000)

    device_fingerprint: Optional[str] = Field(default=None, max_length=128)
    date: Optional[str] = None
    hour: Optional[int] = Field(default=None, ge=0, le=23)
    captured_at: Optional[str] = Field(default=None, max_length=64)
    received_at: Optional[str] = Field(default=None, max_length=64)
    complete: bool = True

    @field_validator("key_categories")
    @classmethod
    def _categories_are_categories(cls, v: str) -> str:
        """Only the five category codes are acceptable.

        This is the structural guarantee behind the privacy claim: if a future
        change to the content script ever started sending real characters, this
        validator rejects the batch instead of storing them.
        """
        if not _CATEGORY_RE.fullmatch(v):
            raise ValueError(
                "key_categories may contain only the codes l, d, s, b and p. "
                "Actual typed characters are never accepted."
            )
        return v

    @field_validator("date")
    @classmethod
    def _date_shape(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _DATE_RE.fullmatch(v):
            raise ValueError("date must be YYYY-MM-DD")
        return v

    @model_validator(mode="after")
    def _backspaces_are_a_subset(self) -> "SessionBatch":
        """Cross-field check.

        This has to be a model validator, not a field validator: Pydantic
        validates fields in declaration order, and `backspace_count` is declared
        before `total_keystrokes`, so a field validator would compare against a
        value that is not populated yet and silently pass everything.
        """
        if self.backspace_count > self.total_keystrokes:
            raise ValueError("backspace_count cannot exceed total_keystrokes")
        return self


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

class ScoreRequest(BaseModel):
    """Deliberately almost empty.

    The user comes from the JWT and the session comes from the database. There
    is nothing useful a client could add here, and every field it might want to
    add is one it must not be allowed to set.
    """
    model_config = STRICT
    recompute: bool = False


# ---------------------------------------------------------------------------
# cognitive mini-tasks
# ---------------------------------------------------------------------------

class TaskScoreRequest(BaseModel):
    model_config = STRICT
    word_recall: Optional[float] = Field(default=None, ge=0, le=5)
    reaction_time_ms: Optional[float] = Field(default=None, ge=50, le=5_000)
    pattern_memory: Optional[float] = Field(default=None, ge=0, le=10)
    letter_scramble_ms: Optional[float] = Field(default=None, ge=200, le=120_000)


# ---------------------------------------------------------------------------
# context
# ---------------------------------------------------------------------------

class ContextRequest(BaseModel):
    model_config = STRICT
    sleep_quality: Optional[int] = Field(default=None, ge=1, le=5)
    stress_level: Optional[int] = Field(default=None, ge=1, le=5)
    device_changed: bool = False
    feeling_unwell: bool = False


# ---------------------------------------------------------------------------
# consent
# ---------------------------------------------------------------------------

class ConsentGrantRequest(BaseModel):
    model_config = STRICT
    doctor_username: str = Field(min_length=3, max_length=64)


class ConsentRevokeRequest(BaseModel):
    model_config = STRICT
    doctor_id: str = Field(min_length=3, max_length=64)
