"""Explainability — turning a score into something a person can act on.

A CogniScore of 62 tells the user nothing. "Your pauses between words are 21%
longer than usual and your corrections are up 14%" tells them something they can
recognise, check against their week, and mention to a doctor. In a health tool
that difference is not a nicety: an unexplained number invites either panic or
dismissal, and both are worse than no number at all.

SHAP is the primary method. A SHAP value is a feature's contribution to *this*
prediction relative to the model's expected output, computed by averaging over
orderings in which features are added — which is what makes the contributions
sum to the prediction and stay consistent between features.

`shap` is optional. Without it we fall back to occlusion attribution: replace
one feature with its baseline mean, re-score, and attribute the change in the
model's decision to that feature. Less principled than Shapley values, honestly
labelled as such in the response via `method`.
"""

from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

from backend.config import FEATURE_LABELS
from ml.anomaly_detector import ANOMALY_FEATURES, AnomalyDetector

try:  # optional dependency
    import shap
    HAS_SHAP = True
except ImportError:  # pragma: no cover - depends on environment
    shap = None
    HAS_SHAP = False


class CogniExplainer:
    """Explains an anomaly decision in terms of the features that drove it."""

    def __init__(self, detector: AnomalyDetector):
        if not detector.is_fitted:
            raise ValueError("Explainer needs a fitted AnomalyDetector.")
        self.detector = detector
        self.explainer = None
        self.background: Optional[np.ndarray] = None
        self.method = "occlusion"

    # -- fitting ------------------------------------------------------------

    def fit(self, baseline_sessions: Sequence[dict]) -> "CogniExplainer":
        X = self.detector._matrix(baseline_sessions)
        if len(X) == 0:
            raise ValueError("No baseline sessions supplied to the explainer.")
        self.background = self.detector.scaler.transform(X)

        if HAS_SHAP:
            try:
                self.explainer = shap.TreeExplainer(self.detector.model)
                self.method = "shap_tree"
            except Exception:
                # Some sklearn/shap version pairs cannot wrap IsolationForest.
                # Fall back rather than fail — and say which method ran.
                self.explainer = None
                self.method = "occlusion"
        return self

    # -- explaining ---------------------------------------------------------

    def _occlusion_values(self, x: np.ndarray) -> np.ndarray:
        """Change in the model's decision when a feature is reset to baseline."""
        base_mean = self.background.mean(axis=0)
        base_decision = float(self.detector.model.decision_function(x.reshape(1, -1))[0])

        values = np.zeros(len(ANOMALY_FEATURES))
        for i in range(len(ANOMALY_FEATURES)):
            probe = x.copy()
            probe[i] = base_mean[i]
            probe_decision = float(
                self.detector.model.decision_function(probe.reshape(1, -1))[0]
            )
            # Positive = removing this feature made the session look MORE normal,
            # i.e. this feature was pushing it toward anomalous.
            values[i] = probe_decision - base_decision
        return values

    def explain(self, session: dict) -> list[dict]:
        """Per-feature [feature_name, value, direction], most important first."""
        X = self.detector._matrix([session])
        xs = self.detector.scaler.transform(X)[0]

        if self.explainer is not None:
            try:
                raw = self.explainer.shap_values(xs.reshape(1, -1))
                values = np.array(raw).reshape(-1)[: len(ANOMALY_FEATURES)]
                # SHAP on IsolationForest explains the *normality* margin, so a
                # negative contribution is what pushes toward anomalous. Flip it
                # so a larger value always means "drove the anomaly more".
                values = -values
            except Exception:
                values = self._occlusion_values(xs)
        else:
            values = self._occlusion_values(xs)

        out = []
        for i, feature in enumerate(ANOMALY_FEATURES):
            out.append({
                "feature": feature,
                "label": FEATURE_LABELS.get(feature, feature),
                "shap_value": round(float(values[i]), 5),
                "direction": "increased" if xs[i] > 0 else "decreased",
                "abs": abs(float(values[i])),
            })

        out.sort(key=lambda d: d["abs"], reverse=True)
        for d in out:
            d.pop("abs")
        return out


# ---------------------------------------------------------------------------
# plain-English formatting
# ---------------------------------------------------------------------------

def format_explanation(
    shap_values: Sequence[dict],
    per_feature: Optional[dict] = None,
    top_n: int = 3,
) -> list[dict]:
    """Render the top contributors as sentences a non-technical user can read.

    Percentages come from the PersonalBaseline deviation (a real, interpretable
    quantity — "21% longer than your usual"), not from the SHAP value itself,
    which is in the model's internal units and means nothing to a reader.
    """
    out = []
    for item in shap_values[:top_n]:
        feature = item["feature"]
        label = item.get("label") or FEATURE_LABELS.get(feature, feature)

        pct, direction = None, item.get("direction", "changed")
        if per_feature and feature in per_feature:
            pct = per_feature[feature].get("percent_change")
            direction = per_feature[feature].get("direction", direction)

        if pct is None:
            text = f"{label}: {direction} compared with your baseline"
        else:
            magnitude = abs(round(pct))
            if magnitude < 1:
                text = f"{label}: essentially unchanged from your baseline"
            else:
                text = f"{label}: {magnitude}% {_phrase_for(feature, direction)}"

        out.append({
            "feature": feature,
            "label": label,
            "text": text,
            "percent_change": pct,
            "direction": direction,
            "shap_value": item.get("shap_value"),
        })
    return out


def _phrase_for(feature: str, direction: str) -> str:
    """The comparative phrase that reads naturally for each feature.

    Returns the whole tail of the sentence, not a bare adjective — "longer than
    usual" and "above your baseline" do not take the same preposition, and
    gluing a fixed "than usual" onto both produces nonsense.
    """
    up = direction == "increased"
    if feature in ("avg_iki_ms", "avg_hold_ms", "mean_correction_ms"):
        return "longer than usual" if up else "shorter than usual"
    if feature == "wpm_estimate":
        return "faster than usual" if up else "slower than usual"
    if feature == "rhythm_variability":
        return "less steady than usual" if up else "steadier than usual"
    if feature == "burst_ratio":
        return "more fluent than usual" if up else "less fluent than usual"
    if feature in ("error_rate", "correction_rate"):
        return "above your baseline" if up else "below your baseline"
    if feature == "long_pause_count":
        return "more frequent than usual" if up else "less frequent than usual"
    return "above your baseline" if up else "below your baseline"
