"""Exploratory pseudo-label classifier.

######################################################################
#                                                                    #
#  THESE LABELS ARE PSEUDO-LABELS FROM ISOLATIONFOREST, NOT CLINICAL  #
#  GROUND TRUTH. THIS MODEL IS EXPLORATORY ONLY AND MUST NOT BE       #
#  PRESENTED AS CLINICALLY VALIDATED.                                 #
#                                                                    #
######################################################################

Why that banner matters, stated plainly because it is a viva question:

Training XGBoost on IsolationForest's own predictions and then reporting
accuracy against those same predictions is **circular validation**. The
classifier is being scored on how well it imitates another unsupervised model,
not on whether either model is right about anything in the world. A high number
here means "XGBoost successfully learned to mimic IsolationForest" — nothing
more. It is not evidence of cognitive detection, and CogniDiff never reports it
as such.

What it *is* legitimately good for: a second, independent read on feature
importance. If ablation, SHAP and XGBoost importance all rank the same features
highly, that convergence is real evidence about our feature engineering, even
though the labels are synthetic.

xgboost is optional; without it a sklearn GradientBoostingClassifier stands in
and the response says which one ran.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

import joblib
import numpy as np

from backend.config import FEATURE_LABELS, MODEL_DIR, SEED
from ml.anomaly_detector import ANOMALY_FEATURES

try:  # optional dependency
    from xgboost import XGBClassifier
    HAS_XGB = True
except ImportError:  # pragma: no cover - depends on environment
    XGBClassifier = None
    HAS_XGB = False

from sklearn.ensemble import GradientBoostingClassifier


class XGBCogniClassifier:
    """Pseudo-label classifier over the anomaly feature set."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.model = None
        self.backend = "xgboost" if HAS_XGB else "sklearn_gbdt"
        self.n_train = 0
        self.label_balance: dict[str, int] = {}

    @staticmethod
    def _matrix(sessions: Sequence[dict]) -> np.ndarray:
        return np.array(
            [[float(s.get(f, 0) or 0) for f in ANOMALY_FEATURES] for s in sessions],
            dtype=float,
        )

    def train(self, sessions: Sequence[dict], labels: Sequence[int]) -> dict:
        """`labels` are IsolationForest is_anomaly predictions — pseudo-labels."""
        X = self._matrix(sessions)
        y = np.asarray([int(bool(v)) for v in labels], dtype=int)

        if len(X) < 10:
            raise ValueError(f"Need at least 10 sessions to train; got {len(X)}.")
        if len(set(y.tolist())) < 2:
            raise ValueError(
                "Pseudo-labels contain a single class — nothing to separate. "
                "This usually means the IsolationForest flagged no anomalies."
            )

        if HAS_XGB:
            self.model = XGBClassifier(
                n_estimators=120, max_depth=3, learning_rate=0.1,
                subsample=0.9, random_state=SEED, eval_metric="logloss",
            )
        else:
            self.model = GradientBoostingClassifier(
                n_estimators=120, max_depth=3, learning_rate=0.1,
                random_state=SEED,
            )

        self.model.fit(X, y)
        self.n_train = len(X)
        self.label_balance = {
            "normal": int((y == 0).sum()),
            "pseudo_anomalous": int((y == 1).sum()),
        }

        return {
            "backend": self.backend,
            "n_train": self.n_train,
            "label_balance": self.label_balance,
            "warning": (
                "Trained on IsolationForest pseudo-labels. Exploratory only — "
                "no clinical validation is claimed or implied."
            ),
        }

    @property
    def is_fitted(self) -> bool:
        return self.model is not None

    def predict(self, session: dict) -> dict:
        if not self.is_fitted:
            raise RuntimeError("Classifier is not fitted.")
        X = self._matrix([session])
        prob = float(self.model.predict_proba(X)[0][1])
        return {
            "anomaly_probability": round(prob, 4),
            "backend": self.backend,
            "is_clinically_validated": False,
        }

    def feature_importance(self) -> list[dict]:
        if not self.is_fitted:
            raise RuntimeError("Classifier is not fitted.")
        importances = np.asarray(self.model.feature_importances_, dtype=float)
        total = importances.sum() or 1.0

        out = [
            {
                "feature": f,
                "label": FEATURE_LABELS.get(f, f),
                "importance": round(float(importances[i]), 5),
                "importance_pct": round(float(importances[i]) / total * 100, 1),
            }
            for i, f in enumerate(ANOMALY_FEATURES)
        ]
        out.sort(key=lambda d: d["importance"], reverse=True)
        for rank, item in enumerate(out, start=1):
            item["rank"] = rank
        return out

    # -- persistence --------------------------------------------------------

    def save(self) -> Path:
        p = Path(MODEL_DIR) / f"xgb_{self.user_id}.pkl"
        p.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, p)
        return p

    @staticmethod
    def load(user_id: str) -> Optional["XGBCogniClassifier"]:
        p = Path(MODEL_DIR) / f"xgb_{user_id}.pkl"
        if not p.exists():
            return None
        try:
            return joblib.load(p)
        except Exception:
            return None
