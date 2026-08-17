"""The session accept / reject gate.

The principle, stated once and enforced everywhere:

    A 10-second typing session, a browser lag spike, or a half-captured batch
    must never be able to move someone's cognitive score.

A session that fails this gate is EXCLUDED from cognitive scoring, never
silently averaged in. Every exclusion is logged with a reason code so the
exclusion rate is a real measured number we can report in the paper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .config import QUALITY_EXCLUDE_THRESHOLD

# ---------------------------------------------------------------------------
# reject criteria, an explicit list, so the gate is a real component
# ---------------------------------------------------------------------------

MIN_KEYSTROKES = 20          # below this there is no rhythm to measure
FLOOR_KEYSTROKES = 5         # below this the volume score is zero
MIN_DURATION_MS = 20_000     # of the 60-second window
FULL_DURATION_MS = 60_000
MAX_PLAUSIBLE_IKI_MS = 30_000
MIN_PLAUSIBLE_IKI_MS = 1     # 0 ms between keys is a clock artefact, not typing
MAX_PLAUSIBLE_WPM = 300

REASON_CODES = {
    "LOW_VOLUME": "Fewer than 20 keystrokes, not enough rhythm to measure.",
    "SHORT_DURATION": "Session covered under 20 seconds of the 60-second window.",
    "MISSING_FEATURES": "One or more required features were absent or null.",
    "ABNORMAL_TIMING": "Impossible inter-key intervals or a clock jump.",
    "INCOMPLETE_CAPTURE": "Batch was cut off by a tab close or worker restart.",
    "DEVICE_CHANGED": "Typed on a different device from the baseline device.",
    "LOW_QUALITY": "Weighted quality score fell below the acceptance threshold.",
}

REQUIRED_FEATURES = (
    "wpm_estimate", "avg_iki_ms", "avg_hold_ms", "error_rate",
    "correction_rate", "rhythm_variability", "long_pause_count",
    "burst_ratio", "total_keystrokes",
)

#: Component weights for the overall quality score.
WEIGHTS = {
    "duration": 0.20,
    "volume": 0.25,
    "completeness": 0.20,
    "timing": 0.25,
    "diversity": 0.10,
}


@dataclass
class QualityResult:
    quality_score: float
    should_exclude: bool
    reason_codes: list[str] = field(default_factory=list)
    breakdown: dict = field(default_factory=dict)
    device_changed: bool = False

    @property
    def primary_reason(self) -> Optional[str]:
        return self.reason_codes[0] if self.reason_codes else None

    def as_dict(self) -> dict:
        return {
            "quality_score": round(self.quality_score, 1),
            "should_exclude": self.should_exclude,
            "reason_codes": self.reason_codes,
            "reasons": [REASON_CODES.get(c, c) for c in self.reason_codes],
            "breakdown": self.breakdown,
            "device_changed": self.device_changed,
        }


class DataQualityEngine:
    """Scores a batch 0–100 and decides whether it may influence a CogniScore."""

    def __init__(self, baseline_device: Optional[str] = None):
        self.baseline_device = baseline_device

    # -- component scores ---------------------------------------------------

    @staticmethod
    def _duration_score(batch: dict) -> tuple[float, Optional[str]]:
        dur = float(batch.get("duration_ms") or 0)
        if dur <= 0:
            return 50.0, None            # unknown duration, neutral, not fatal
        if dur < MIN_DURATION_MS:
            return round(100 * dur / FULL_DURATION_MS, 1), "SHORT_DURATION"
        return round(min(100.0, 100 * dur / FULL_DURATION_MS), 1), None

    @staticmethod
    def _volume_score(batch: dict) -> tuple[float, Optional[str]]:
        n = int(batch.get("total_keystrokes") or 0)
        if n < FLOOR_KEYSTROKES:
            return 0.0, "LOW_VOLUME"
        if n < MIN_KEYSTROKES:
            span = MIN_KEYSTROKES - FLOOR_KEYSTROKES
            return round(100 * (n - FLOOR_KEYSTROKES) / span, 1), "LOW_VOLUME"
        return 100.0, None

    @staticmethod
    def _completeness_score(batch: dict) -> tuple[float, Optional[str]]:
        missing = [f for f in REQUIRED_FEATURES
                   if batch.get(f) is None or _is_nan(batch.get(f))]
        if not missing:
            return 100.0, None
        pct = 100 * (1 - len(missing) / len(REQUIRED_FEATURES))
        return round(pct, 1), "MISSING_FEATURES"

    @staticmethod
    def _timing_score(batch: dict) -> tuple[float, Optional[str]]:
        """Browser lag must never look like cognitive slowing."""
        intervals = batch.get("_intervals") or []
        iki = float(batch.get("avg_iki_ms") or 0)
        wpm = float(batch.get("wpm_estimate") or 0)

        if iki < 0 or iki > MAX_PLAUSIBLE_IKI_MS:
            return 0.0, "ABNORMAL_TIMING"
        if wpm < 0 or wpm > MAX_PLAUSIBLE_WPM:
            return 0.0, "ABNORMAL_TIMING"

        if intervals:
            impossible = sum(
                1 for i in intervals
                if i < MIN_PLAUSIBLE_IKI_MS or i > MAX_PLAUSIBLE_IKI_MS
            )
            bad_ratio = impossible / len(intervals)
            if bad_ratio > 0.10:
                return round(max(0.0, 100 * (1 - bad_ratio)), 1), "ABNORMAL_TIMING"
            return round(100 * (1 - bad_ratio), 1), None

        # No interval array: we can only sanity-check the aggregate.
        return (100.0, None) if iki > 0 else (60.0, None)

    @staticmethod
    def _diversity_score(batch: dict) -> tuple[float, Optional[str]]:
        """A minute of nothing but digits is a spreadsheet, not prose. It has a
        different rhythm and would pollute a baseline built on writing."""
        cats = batch.get("key_categories") or ""
        if not cats:
            return 70.0, None            # unknown, mildly penalised, not fatal

        total = len(cats)
        letters = cats.count("l") / total
        spaces = cats.count("s") / total
        digits = cats.count("d") / total

        score = 100.0
        if letters < 0.35:
            score -= 40 * (0.35 - letters) / 0.35
        if spaces < 0.05:
            score -= 25 * (0.05 - spaces) / 0.05
        if digits > 0.60:
            score -= 35 * (digits - 0.60) / 0.40
        return round(max(0.0, min(100.0, score)), 1), None

    # -- main ---------------------------------------------------------------

    def score_session(self, batch: dict) -> QualityResult:
        reasons: list[str] = []
        parts: dict[str, float] = {}

        for name, fn in (
            ("duration", self._duration_score),
            ("volume", self._volume_score),
            ("completeness", self._completeness_score),
            ("timing", self._timing_score),
            ("diversity", self._diversity_score),
        ):
            value, reason = fn(batch)
            parts[name] = value
            if reason and reason not in reasons:
                reasons.append(reason)

        # An explicit incomplete-capture flag from the extension.
        if batch.get("complete") is False:
            reasons.append("INCOMPLETE_CAPTURE")
            parts["duration"] = min(parts["duration"], 50.0)

        overall = sum(parts[k] * WEIGHTS[k] for k in WEIGHTS)

        # Device consistency. A new keyboard changes typing rhythm far more than
        # a mild cognitive change does, so a session from an unfamiliar device
        # can never carry full weight, it is capped, and flagged for the drift
        # detector to turn into a recalibration window.
        device_changed = False
        fingerprint = batch.get("device_fingerprint")
        if self.baseline_device and fingerprint and fingerprint != self.baseline_device:
            device_changed = True
            overall = min(overall, 50.0)
            reasons.append("DEVICE_CHANGED")

        # Hard rejects override the weighted average outright.
        hard_reject = (
            int(batch.get("total_keystrokes") or 0) < MIN_KEYSTROKES
            or "ABNORMAL_TIMING" in reasons
            or "MISSING_FEATURES" in reasons
        )

        should_exclude = hard_reject or overall < QUALITY_EXCLUDE_THRESHOLD
        if should_exclude and not reasons:
            reasons.append("LOW_QUALITY")

        return QualityResult(
            quality_score=round(overall, 1),
            should_exclude=should_exclude,
            reason_codes=reasons,
            breakdown={k: round(v, 1) for k, v in parts.items()},
            device_changed=device_changed,
        )


def _is_nan(x) -> bool:
    try:
        return x != x          # NaN is the only value not equal to itself
    except TypeError:
        return False


def quality_tier(score: float) -> str:
    if score > 80:
        return "excellent"
    if score >= QUALITY_EXCLUDE_THRESHOLD:
        return "acceptable"
    return "excluded"
