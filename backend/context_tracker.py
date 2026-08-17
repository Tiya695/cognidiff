"""Context awareness — separating "tired" from "changed".

Typing performance is influenced by a lot of things that have nothing to do with
cognition. A user who slept four hours, is stressed about an exam, and has the
flu will type measurably worse — and a monitoring tool that reads that as
cognitive change is a false-alarm generator.

So the user can optionally tell us. When they do, the raw score is left intact
and a *separate* adjusted score is stored alongside it. Both are shown. We never
overwrite the measurement with the adjustment: the raw number is the evidence,
the adjusted number is the interpretation, and a reviewer can see both.
"""

from __future__ import annotations

from typing import Optional

from . import database as db

#: Tolerance points added to the raw score when a known non-cognitive factor is
#: present. Deliberately modest — context should soften a reading, never erase
#: it. The values are documented here so the dashboard, the tests and the paper
#: all quote the same numbers.
TOLERANCE = {
    "poor_sleep": 5,        # sleep_quality of 1 or 2
    "high_stress": 3,       # stress_level of 4 or 5
    "feeling_unwell": 10,
}

MAX_TOLERANCE = 18          # cap, so context can never manufacture a good day


class ContextTracker:
    """Stores daily self-reported context and applies it to a score."""

    @staticmethod
    def save(
        user_id: str,
        date: str,
        sleep_quality: Optional[int] = None,
        stress_level: Optional[int] = None,
        device_changed: bool = False,
        feeling_unwell: bool = False,
    ) -> dict:
        db.execute(
            """
            INSERT INTO daily_context
                (user_id, date, sleep_quality, stress_level, device_changed,
                 feeling_unwell, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, date) DO UPDATE SET
                sleep_quality  = excluded.sleep_quality,
                stress_level   = excluded.stress_level,
                device_changed = excluded.device_changed,
                feeling_unwell = excluded.feeling_unwell
            """,
            (user_id, date, sleep_quality, stress_level,
             int(bool(device_changed)), int(bool(feeling_unwell)), db.utcnow()),
        )
        return ContextTracker.get(user_id, date) or {}

    @staticmethod
    def get(user_id: str, date: str) -> Optional[dict]:
        row = db.query_one(
            "SELECT * FROM daily_context WHERE user_id = ? AND date = ?",
            (user_id, date),
        )
        if row:
            row["device_changed"] = bool(row["device_changed"])
            row["feeling_unwell"] = bool(row["feeling_unwell"])
        return row

    @staticmethod
    def adjust_score(cogni_score: float, context: Optional[dict]) -> dict:
        """Apply tolerance points. Returns raw and adjusted scores plus reasons."""
        if not context:
            return {
                "raw_score": round(float(cogni_score), 1),
                "adjusted_score": round(float(cogni_score), 1),
                "context_adjusted": False,
                "tolerance_applied": 0,
                "reasons": [],
                "exclude_from_trend": False,
            }

        tolerance = 0
        reasons: list[str] = []

        sleep = context.get("sleep_quality")
        if sleep is not None and int(sleep) <= 2:
            tolerance += TOLERANCE["poor_sleep"]
            reasons.append(f"Poor sleep reported (+{TOLERANCE['poor_sleep']})")

        stress = context.get("stress_level")
        if stress is not None and int(stress) >= 4:
            tolerance += TOLERANCE["high_stress"]
            reasons.append(f"High stress reported (+{TOLERANCE['high_stress']})")

        if context.get("feeling_unwell"):
            tolerance += TOLERANCE["feeling_unwell"]
            reasons.append(f"Feeling unwell reported (+{TOLERANCE['feeling_unwell']})")

        tolerance = min(tolerance, MAX_TOLERANCE)
        adjusted = min(100.0, float(cogni_score) + tolerance)

        # A device change does not get tolerance points — it gets the session
        # pulled out of the trend entirely. Adding points would still let a new
        # keyboard bend the curve; excluding it is the honest handling.
        exclude = bool(context.get("device_changed"))
        if exclude:
            reasons.append("Different device reported — excluded from trend")

        return {
            "raw_score": round(float(cogni_score), 1),
            "adjusted_score": round(adjusted, 1),
            "context_adjusted": tolerance > 0,
            "tolerance_applied": tolerance,
            "reasons": reasons,
            "exclude_from_trend": exclude,
        }
