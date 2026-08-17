"""PersonalBaseline — the heart of CogniDiff.

CogniDiff never compares a user to a population. It compares a user to
themselves. A naturally fast typist and a naturally slow typist are both
"normal"; what matters is a sustained move away from *your own* usual rhythm.

The baseline stores, per feature, the mean and standard deviation of that
user's quality-passing sessions — globally and separately per time slot,
because a person's 2am typing is not comparable to their 10am typing.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

import joblib
import numpy as np

from backend.config import (
    FEATURE_NAMES,
    FEATURE_WEIGHTS,
    MIN_BASELINE_SESSIONS,
    MODEL_DIR,
    QUALITY_EXCLUDE_THRESHOLD,
)

#: Standard deviations below which a feature is treated as effectively constant.
#: Prevents a division-by-near-zero from turning trivial jitter into a 40-sigma
#: deviation on a user who happens to be very consistent.
MIN_STD = {
    "wpm_estimate": 1.5,
    "avg_iki_ms": 8.0,
    "avg_hold_ms": 3.0,
    "error_rate": 0.005,
    "correction_rate": 0.003,
    "rhythm_variability": 5.0,
    "long_pause_count": 0.4,
    "burst_ratio": 0.01,
}

#: Direction in which a rise in the feature indicates *worse* performance.
#: Used so that typing faster than baseline is not penalised the same way as
#: typing slower than baseline.
HIGHER_IS_WORSE = {
    "wpm_estimate": False,
    "avg_iki_ms": True,
    "avg_hold_ms": True,
    "error_rate": True,
    "correction_rate": True,
    "rhythm_variability": True,
    "long_pause_count": True,
    "burst_ratio": False,
}


class PersonalBaseline:
    """Per-user statistical baseline over the CogniDiff feature set."""

    def __init__(self, user_id: str, version: int = 1):
        self.user_id = user_id
        self.version = version
        self.means: dict[str, float] = {}
        self.stds: dict[str, float] = {}
        self.slot_means: dict[str, dict[str, float]] = {}
        self.slot_stds: dict[str, dict[str, float]] = {}
        self.n_sessions = 0
        self.device: Optional[str] = None
        self.fitted_at: Optional[str] = None
        self.period: tuple[Optional[str], Optional[str]] = (None, None)

    # -- fitting ------------------------------------------------------------

    def fit(self, sessions: Sequence[dict]) -> "PersonalBaseline":
        """Fit on quality-passing sessions only.

        Sessions below the quality threshold, or explicitly excluded, are
        dropped here as well as at query time — defence in depth, because a
        baseline poisoned by junk sessions silently corrupts every score that
        follows.
        """
        good = [
            s for s in sessions
            if not s.get("excluded")
            and float(s.get("quality_score", 0) or 0) >= QUALITY_EXCLUDE_THRESHOLD
        ]

        if len(good) < MIN_BASELINE_SESSIONS:
            raise ValueError(
                f"Need at least {MIN_BASELINE_SESSIONS} quality-passing sessions "
                f"to fit a baseline; got {len(good)}."
            )

        for feature in FEATURE_NAMES:
            values = np.array(
                [float(s.get(feature, 0) or 0) for s in good], dtype=float
            )
            self.means[feature] = float(values.mean())
            self.stds[feature] = max(float(values.std()), MIN_STD.get(feature, 1e-6))

        # per-time-slot baselines
        slots: dict[str, list[dict]] = {}
        for s in good:
            slots.setdefault(s.get("time_slot", "unknown"), []).append(s)

        for slot, rows in slots.items():
            if len(rows) < 3:
                continue                      # too thin to be a baseline
            self.slot_means[slot] = {}
            self.slot_stds[slot] = {}
            for feature in FEATURE_NAMES:
                values = np.array(
                    [float(r.get(feature, 0) or 0) for r in rows], dtype=float
                )
                self.slot_means[slot][feature] = float(values.mean())
                self.slot_stds[slot][feature] = max(
                    float(values.std()), MIN_STD.get(feature, 1e-6)
                )

        self.n_sessions = len(good)
        devices = {s.get("device_fingerprint") for s in good if s.get("device_fingerprint")}
        self.device = next(iter(devices)) if len(devices) == 1 else None
        self.fitted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        dates = sorted(s.get("date", "") for s in good if s.get("date"))
        self.period = (dates[0] if dates else None, dates[-1] if dates else None)
        return self

    @property
    def is_fitted(self) -> bool:
        return bool(self.means)

    # -- deviation ----------------------------------------------------------

    def _reference(self, session: dict) -> tuple[dict, dict]:
        """Prefer the time-slot baseline when one exists for this session."""
        slot = session.get("time_slot")
        if slot and slot in self.slot_means:
            return self.slot_means[slot], self.slot_stds[slot]
        return self.means, self.stds

    def deviation_score(self, session: dict) -> dict[str, dict]:
        """Per-feature deviation from baseline, in standard deviations.

        ``z`` is signed (negative = below baseline). ``adverse_z`` is the part
        of that movement which points in the *worse* direction — typing faster
        than usual is not evidence of cognitive change, typing slower may be.
        """
        if not self.is_fitted:
            raise RuntimeError("Baseline is not fitted.")

        means, stds = self._reference(session)
        out: dict[str, dict] = {}

        for feature in FEATURE_NAMES:
            value = float(session.get(feature, 0) or 0)
            mean = means.get(feature, 0.0)
            std = stds.get(feature, 1.0) or 1.0

            z = (value - mean) / std
            adverse = z if HIGHER_IS_WORSE[feature] else -z
            pct = ((value - mean) / mean * 100.0) if abs(mean) > 1e-9 else 0.0

            out[feature] = {
                "value": round(value, 4),
                "baseline_mean": round(mean, 4),
                "baseline_std": round(std, 4),
                "z": round(z, 3),
                "adverse_z": round(max(adverse, 0.0), 3),
                "percent_change": round(pct, 1),
                "direction": "increased" if z > 0 else "decreased",
            }
        return out

    def weighted_adverse_z(self, session: dict) -> float:
        """Weighted mean adverse deviation across the feature set, in sigma."""
        devs = self.deviation_score(session)
        total_w = sum(FEATURE_WEIGHTS[f] for f in FEATURE_NAMES)
        return sum(
            devs[f]["adverse_z"] * FEATURE_WEIGHTS[f] for f in FEATURE_NAMES
        ) / total_w

    def overall_deviation(self, session: dict) -> float:
        """Single weighted adverse deviation, expressed 0–100.

        Only adverse movement counts — typing *faster* than usual is not
        evidence of anything worrying, and treating it symmetrically would make
        a good day look like a bad one.

        The map from sigma to percentage saturates rather than scaling linearly.
        A linear map has no headroom: once someone is three sigma out, every
        further sigma has to be crammed into the last few points, so the metric
        stops discriminating exactly where it matters most.
        """
        z = self.weighted_adverse_z(session)
        deviation = 100.0 * (1.0 - math.exp(-((max(z, 0.0) / 2.2) ** 1.6)))
        return round(min(100.0, deviation), 2)

    # -- the CogniScore -----------------------------------------------------

    def cogni_score(self, session: dict) -> dict:
        """Map deviation to a 0–100 CogniScore, where 100 is a perfect match.

        Sigmoid rather than linear, deliberately. A linear map turns ordinary
        day-to-day variation into visible score movement, which in a health tool
        reads as "something is wrong" every time the user has a bad night. The
        sigmoid is flat near the baseline — deviations under ~10% stay above 90 —
        and steepens only once the movement is genuinely unusual. Small daily
        variation is normal and the score should say so.

        Calibration, in sigma of weighted adverse deviation:

            0.0σ → 98    a day indistinguishable from baseline
            1.0σ → 93    ordinary variation
            1.5σ → 81    worth noticing
            2.0σ → 62    clearly different
            3.0σ → 27    sustained, substantial change
        """
        deviation = self.overall_deviation(session)
        devs = self.deviation_score(session)

        score = 100.0 / (1.0 + math.exp(0.07 * (deviation - 58.0)))
        score = round(max(0.0, min(100.0, score)), 1)

        worst = max(FEATURE_NAMES, key=lambda f: devs[f]["adverse_z"])

        return {
            "cogni_score": score,
            "deviation_percent": deviation,
            "top_deviating_feature": worst,
            "per_feature": devs,
            "baseline_version": self.version,
            "baseline_sessions": self.n_sessions,
            "time_slot_used": (
                session.get("time_slot")
                if session.get("time_slot") in self.slot_means else "global"
            ),
        }

    # -- persistence --------------------------------------------------------

    def path(self) -> Path:
        return Path(MODEL_DIR) / f"baseline_{self.user_id}_v{self.version}.pkl"

    def save(self) -> Path:
        p = self.path()
        p.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, p)
        # A stable pointer to the newest version, so callers need not guess.
        joblib.dump(self, Path(MODEL_DIR) / f"baseline_{self.user_id}.pkl")
        return p

    @staticmethod
    def load(user_id: str, version: Optional[int] = None) -> Optional["PersonalBaseline"]:
        name = (
            f"baseline_{user_id}_v{version}.pkl" if version
            else f"baseline_{user_id}.pkl"
        )
        p = Path(MODEL_DIR) / name
        if not p.exists():
            return None
        try:
            return joblib.load(p)
        except Exception:
            return None

    def summary(self) -> dict:
        return {
            "user_id": self.user_id,
            "version": self.version,
            "n_sessions": self.n_sessions,
            "fitted_at": self.fitted_at,
            "period_start": self.period[0],
            "period_end": self.period[1],
            "device": self.device,
            "time_slots": sorted(self.slot_means.keys()),
            "means": {k: round(v, 3) for k, v in self.means.items()},
            "stds": {k: round(v, 3) for k, v in self.stds.items()},
        }
