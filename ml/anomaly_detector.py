"""Unsupervised anomaly detection with IsolationForest.

Why an Isolation Forest: we have no labels. Nobody has told us which of this
user's sessions were "cognitively off", and manufacturing such labels would be
dishonest. An Isolation Forest needs none — it builds random trees and measures
how few splits it takes to isolate a point. Ordinary sessions sit inside dense
regions and take many splits; unusual ones fall out early. That gives an outlier
score with no ground truth at all.

It complements PersonalBaseline rather than duplicating it. The baseline asks
"how far is this feature from your mean?", one feature at a time. The forest
asks "is this *combination* of features one I have seen from you before?" — it
catches sessions where every individual feature looks acceptable but the
pattern as a whole does not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from backend.config import MODEL_DIR, QUALITY_EXCLUDE_THRESHOLD, SEED

#: Deliberately a subset of the full feature set. These five carry the timing
#: signal; the rest are correlated derivatives that would let the forest
#: double-count the same evidence.
ANOMALY_FEATURES = [
    "wpm_estimate",
    "avg_iki_ms",
    "error_rate",
    "rhythm_variability",
    "long_pause_count",
]

#: Expected proportion of outliers. 0.08 is tuned against the false-positive
#: target in docs/false_positive_test.md — raising it makes the detector
#: jumpier, which in a health tool means more unnecessary anxiety.
CONTAMINATION = 0.08


class AnomalyDetector:
    def __init__(self, user_id: str, contamination: float = CONTAMINATION):
        self.user_id = user_id
        self.contamination = contamination
        self.model: Optional[IsolationForest] = None
        self.scaler: Optional[StandardScaler] = None
        self.n_train = 0
        self._score_std = 1.0

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _matrix(sessions: Sequence[dict]) -> np.ndarray:
        return np.array(
            [[float(s.get(f, 0) or 0) for f in ANOMALY_FEATURES] for s in sessions],
            dtype=float,
        )

    # -- fit / predict ------------------------------------------------------

    def fit(self, sessions: Sequence[dict]) -> "AnomalyDetector":
        good = [
            s for s in sessions
            if not s.get("excluded")
            and float(s.get("quality_score", 0) or 0) >= QUALITY_EXCLUDE_THRESHOLD
        ]
        if len(good) < 10:
            raise ValueError(
                f"Need at least 10 quality-passing sessions to fit; got {len(good)}."
            )

        X = self._matrix(good)
        self.scaler = StandardScaler().fit(X)
        Xs = self.scaler.transform(X)

        self.model = IsolationForest(
            n_estimators=200,
            contamination=self.contamination,
            random_state=SEED,
            bootstrap=False,
        ).fit(Xs)

        train_scores = self.model.score_samples(Xs)
        self._score_std = float(train_scores.std()) or 1.0
        self.n_train = len(good)
        return self

    @property
    def is_fitted(self) -> bool:
        return self.model is not None

    def predict(self, session: dict) -> dict:
        """Return is_anomaly, a signed anomaly score, and a confidence."""
        if not self.is_fitted:
            raise RuntimeError("AnomalyDetector is not fitted.")

        X = self.scaler.transform(self._matrix([session]))
        label = int(self.model.predict(X)[0])            # 1 normal, -1 anomaly
        raw = float(self.model.score_samples(X)[0])      # higher = more normal
        decision = float(self.model.decision_function(X)[0])

        # Map the decision margin to 0..1. A point sitting right on the
        # boundary should not be reported as a confident call either way.
        confidence = float(min(1.0, abs(decision) / (2.0 * self._score_std)))

        return {
            "is_anomaly": label == -1,
            "anomaly_score": round(raw, 4),
            "decision": round(decision, 4),
            "confidence": round(confidence, 3),
            "n_train": self.n_train,
        }

    def predict_batch(self, sessions: Sequence[dict]) -> list[dict]:
        return [self.predict(s) for s in sessions]

    # -- persistence --------------------------------------------------------

    def path(self) -> Path:
        return Path(MODEL_DIR) / f"anomaly_{self.user_id}.pkl"

    def save(self) -> Path:
        p = self.path()
        p.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, p)
        return p

    @staticmethod
    def load(user_id: str) -> Optional["AnomalyDetector"]:
        p = Path(MODEL_DIR) / f"anomaly_{user_id}.pkl"
        if not p.exists():
            return None
        try:
            return joblib.load(p)
        except Exception:
            return None


# ---------------------------------------------------------------------------
# dual confirmation
# ---------------------------------------------------------------------------

DEVIATION_THRESHOLD = 25.0


def dual_confirmation(deviation_percent: float, anomaly: Optional[dict]) -> dict:
    """Flag a session as concerning only when BOTH models agree.

    The statistical baseline and the Isolation Forest fail in different ways.
    The baseline over-reacts to one feature drifting; the forest over-reacts to
    an unusual but harmless combination. Requiring both to fire at once means a
    single model's characteristic false positive cannot raise a flag on its own —
    which is the whole point in a tool where a false alarm causes real anxiety.
    """
    statistical = deviation_percent > DEVIATION_THRESHOLD
    ml = bool(anomaly and anomaly.get("is_anomaly"))

    if statistical and ml:
        agreement = "BOTH_AGREE_ANOMALOUS"
    elif statistical or ml:
        agreement = "MODELS_DISAGREE"
    else:
        agreement = "BOTH_AGREE_NORMAL"

    return {
        "concerning": statistical and ml,
        "statistical_flag": statistical,
        "ml_flag": ml,
        "agreement": agreement,
        "deviation_threshold": DEVIATION_THRESHOLD,
    }
