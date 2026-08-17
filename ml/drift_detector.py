"""Model drift — and the distinction that matters most in this project.

There are two very different reasons a person's typing baseline stops fitting:

  ABRUPT_ENVIRONMENTAL — they bought a new keyboard, switched laptops, changed
      keyboard layout or language. The change is sudden, has a known external
      cause, and says nothing about them. The correct response is to *suspend
      judgement*, recalibrate, and raise no alerts in the meantime.

  GRADUAL_UNEXPLAINED — a slow shift with no environmental cause. This is
      precisely the signal CogniDiff exists to detect, and it must NOT be
      recalibrated away. A system that quietly refits its baseline whenever the
      data drifts can never detect gradual decline, because it defines the
      decline as the new normal.

Getting this backwards is the difference between a monitoring tool and a
false-alarm generator — in one direction, and a tool that detects nothing at all
in the other.
"""

from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

from backend.config import FEATURE_NAMES, RECALIBRATION_SESSIONS
from ml.baseline import PersonalBaseline

DRIFT_SIGMA = 2.0            # feature mean shift that counts as drifted
ABRUPT_WINDOW = 5            # sessions either side of a fingerprint change
GRADUAL_MIN_DAYS = 14        # a shift must span this long to count as gradual


class ModelDriftDetector:
    """Compares a recent window against the fitted baseline distributions."""

    def __init__(self, baseline: PersonalBaseline):
        if not baseline.is_fitted:
            raise ValueError("Drift detection needs a fitted baseline.")
        self.baseline = baseline

    # -- drift detection ----------------------------------------------------

    def check_drift(self, recent_sessions: Sequence[dict], window: int = 7) -> dict:
        """Which features have moved more than 2 sigma from baseline."""
        recent = [s for s in recent_sessions if not s.get("excluded")][-window * 3:]
        if len(recent) < 3:
            return {
                "drifted_features": [],
                "drift_severity": "unknown",
                "recommended_action": "monitor",
                "n_recent": len(recent),
                "note": "Not enough recent sessions to assess drift.",
            }

        drifted = []
        for feature in FEATURE_NAMES:
            values = np.array(
                [float(s.get(feature, 0) or 0) for s in recent], dtype=float
            )
            mean = self.baseline.means.get(feature, 0.0)
            std = self.baseline.stds.get(feature, 1.0) or 1.0
            shift = (values.mean() - mean) / std

            if abs(shift) >= DRIFT_SIGMA:
                drifted.append({
                    "feature": feature,
                    "shift_sigma": round(float(shift), 2),
                    "baseline_mean": round(mean, 3),
                    "recent_mean": round(float(values.mean()), 3),
                    "direction": "increased" if shift > 0 else "decreased",
                })

        n = len(drifted)
        if n == 0:
            severity, action = "none", "monitor"
        elif n <= 1:
            severity, action = "low", "monitor"
        elif n <= 3:
            severity, action = "medium", "monitor"
        else:
            severity, action = "high", "refit_baseline"

        return {
            "drifted_features": sorted(
                drifted, key=lambda d: abs(d["shift_sigma"]), reverse=True
            ),
            "drift_severity": severity,
            "recommended_action": action,
            "n_recent": len(recent),
            "threshold_sigma": DRIFT_SIGMA,
        }

    # -- the important half: telling the two causes apart -------------------

    def classify_drift(self, sessions: Sequence[dict]) -> dict:
        """Return ABRUPT_ENVIRONMENTAL, GRADUAL_UNEXPLAINED or STABLE."""
        usable = [s for s in sessions if not s.get("excluded")]
        if len(usable) < 6:
            return {
                "classification": "STABLE",
                "reason": "Not enough sessions to classify drift.",
                "confidence": "low",
            }

        # 1. Environmental cause: did the device fingerprint change, and did the
        #    features step at the same moment?
        fingerprints = [s.get("device_fingerprint") for s in usable]
        change_idx = None
        for i in range(1, len(fingerprints)):
            if fingerprints[i] and fingerprints[i - 1] and fingerprints[i] != fingerprints[i - 1]:
                change_idx = i
                break

        if change_idx is not None:
            before = usable[max(0, change_idx - ABRUPT_WINDOW):change_idx]
            after = usable[change_idx:change_idx + ABRUPT_WINDOW]
            step = self._mean_abs_step(before, after)
            return {
                "classification": "ABRUPT_ENVIRONMENTAL",
                "reason": (
                    "Device fingerprint changed and the feature means stepped at "
                    "the same point. A new setup, not a new person."
                ),
                "change_index": change_idx,
                "step_sigma": round(step, 2),
                "confidence": "high" if step > 1.0 else "moderate",
                "recommended_action": "recalibrate",
            }

        # 2. No environmental cause. Is the 7-day rolling mean moving steadily?
        trend = self._rolling_trend(usable)
        span_days = len({s.get("date") for s in usable if s.get("date")})

        if abs(trend["slope_sigma_per_session"]) > 0.02 and span_days >= GRADUAL_MIN_DAYS:
            return {
                "classification": "GRADUAL_UNEXPLAINED",
                "reason": (
                    "The 7-day rolling mean is moving steadily with no device or "
                    "environment change to explain it. This is the pattern "
                    "CogniDiff is designed to surface — it is NOT recalibrated away."
                ),
                "slope_sigma_per_session": trend["slope_sigma_per_session"],
                "span_days": span_days,
                "confidence": "moderate",
                "recommended_action": "alert_and_keep_baseline",
            }

        return {
            "classification": "STABLE",
            "reason": "No environmental change and no sustained directional shift.",
            "slope_sigma_per_session": trend["slope_sigma_per_session"],
            "span_days": span_days,
            "confidence": "high",
            "recommended_action": "monitor",
        }

    # -- helpers ------------------------------------------------------------

    def _mean_abs_step(self, before: Sequence[dict], after: Sequence[dict]) -> float:
        if not before or not after:
            return 0.0
        steps = []
        for feature in FEATURE_NAMES:
            std = self.baseline.stds.get(feature, 1.0) or 1.0
            b = np.mean([float(s.get(feature, 0) or 0) for s in before])
            a = np.mean([float(s.get(feature, 0) or 0) for s in after])
            steps.append(abs(a - b) / std)
        return float(np.mean(steps))

    def _rolling_trend(self, sessions: Sequence[dict], window: int = 7) -> dict:
        """Least-squares slope of the adverse-deviation rolling mean, in sigma
        per session."""
        if len(sessions) < window + 2:
            return {"slope_sigma_per_session": 0.0}

        series = []
        for s in sessions:
            devs = self.baseline.deviation_score(s)
            series.append(np.mean([devs[f]["adverse_z"] for f in FEATURE_NAMES]))

        arr = np.asarray(series, dtype=float)
        kernel = np.ones(window) / window
        rolled = np.convolve(arr, kernel, mode="valid")

        x = np.arange(len(rolled), dtype=float)
        slope = float(np.polyfit(x, rolled, 1)[0]) if len(rolled) >= 2 else 0.0
        return {"slope_sigma_per_session": round(slope, 4)}


# ---------------------------------------------------------------------------
# baseline status machine
# ---------------------------------------------------------------------------

STATUS_ACTIVE = "ACTIVE"
STATUS_RECALIBRATING = "RECALIBRATING"
STATUS_INSUFFICIENT = "INSUFFICIENT_DATA"


def recalibration_progress(sessions_since_change: int) -> dict:
    """How far through the recalibration window we are."""
    needed = RECALIBRATION_SESSIONS
    done = min(int(sessions_since_change), needed)
    return {
        "sessions_collected": done,
        "sessions_required": needed,
        "percent": round(100 * done / needed, 1),
        "complete": done >= needed,
    }
