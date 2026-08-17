"""Ablation study — quantifying what each feature actually contributes.

Remove one feature, refit the detector, and measure how much worse it gets. A
feature whose removal changes nothing is a feature that was not doing anything,
however plausible it sounded when we designed it.

This is one of three independent views on feature importance. The other two are
SHAP (ml/explainer.py) and the XGBoost importance ranking (ml/xgb_model.py).
When all three agree on the ranking, that convergence is real evidence about the
feature engineering — far stronger than any single method's word for it. Where
they disagree, the disagreement itself is the finding and gets reported.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from backend.config import FEATURE_LABELS, SEED
from ml.anomaly_detector import ANOMALY_FEATURES, CONTAMINATION


def _fit_and_score(
    sessions: Sequence[dict],
    features: Sequence[str],
) -> np.ndarray:
    X = np.array(
        [[float(s.get(f, 0) or 0) for f in features] for s in sessions],
        dtype=float,
    )
    Xs = StandardScaler().fit_transform(X)
    model = IsolationForest(
        n_estimators=200, contamination=CONTAMINATION, random_state=SEED
    ).fit(Xs)
    return model.predict(Xs)          # 1 normal, -1 anomaly


def run_ablation(
    sessions: Sequence[dict],
    features: Sequence[str] = tuple(ANOMALY_FEATURES),
) -> dict:
    """Leave-one-feature-out impact on the detector's decisions.

    The metric is the proportion of sessions whose anomaly verdict *flips* when
    the feature is withheld. A high flip rate means the detector was leaning on
    that feature to make its calls.
    """
    features = list(features)
    if len(sessions) < 15:
        raise ValueError(
            f"Ablation needs at least 15 quality sessions; got {len(sessions)}."
        )

    full = _fit_and_score(sessions, features)
    full_anomalies = int((full == -1).sum())

    results = []
    for feature in features:
        reduced = [f for f in features if f != feature]
        if not reduced:
            continue

        ablated = _fit_and_score(sessions, reduced)
        flips = int((ablated != full).sum())
        flip_rate = 100.0 * flips / len(full)
        ablated_anomalies = int((ablated == -1).sum())

        detection_change = (
            100.0 * (ablated_anomalies - full_anomalies) / full_anomalies
            if full_anomalies else 0.0
        )

        results.append({
            "feature_name": feature,
            "label": FEATURE_LABELS.get(feature, feature),
            "decision_flip_rate_percent": round(flip_rate, 2),
            "anomaly_detection_change_percent": round(detection_change, 2),
            "anomalies_with_feature": full_anomalies,
            "anomalies_without_feature": ablated_anomalies,
        })

    # Rank by how much the detector's behaviour changed without the feature.
    results.sort(key=lambda r: r["decision_flip_rate_percent"], reverse=True)
    for rank, r in enumerate(results, start=1):
        r["importance_rank"] = rank

    return {
        "n_sessions": len(sessions),
        "features_tested": features,
        "baseline_anomalies": full_anomalies,
        "results": results,
        "most_important": results[0]["feature_name"] if results else None,
        "least_important": results[-1]["feature_name"] if results else None,
        "method": "leave-one-out IsolationForest decision flip rate",
        "seed": SEED,
    }


def compare_methods(
    ablation_result: dict,
    shap_ranking: Sequence[dict],
    xgb_ranking: Sequence[dict],
) -> dict:
    """Convergent-validity check across the three importance methods."""
    def order(items, key):
        return [i[key] for i in items]

    abl = order(ablation_result.get("results", []), "feature_name")
    shp = order(shap_ranking, "feature")
    xgb = order(xgb_ranking, "feature")

    common = [f for f in abl if f in shp and f in xgb]
    if len(common) < 2:
        return {"comparable": False, "note": "Not enough overlapping features."}

    def rank_map(seq):
        return {f: i for i, f in enumerate(seq)}

    ra, rs, rx = rank_map(abl), rank_map(shp), rank_map(xgb)

    def spearman(m1, m2):
        d2 = sum((m1[f] - m2[f]) ** 2 for f in common)
        n = len(common)
        return round(1 - (6 * d2) / (n * (n * n - 1)), 3) if n > 1 else 0.0

    agreements = {
        "ablation_vs_shap": spearman(ra, rs),
        "ablation_vs_xgboost": spearman(ra, rx),
        "shap_vs_xgboost": spearman(rs, rx),
    }
    mean_rho = round(sum(agreements.values()) / len(agreements), 3)

    return {
        "comparable": True,
        "features_compared": common,
        "spearman_rho": agreements,
        "mean_agreement": mean_rho,
        "interpretation": (
            "Strong convergent validity — three independent methods rank the "
            "features consistently."
            if mean_rho > 0.6 else
            "Methods disagree on ranking. Report the disagreement rather than "
            "picking the most flattering ordering."
        ),
        "top_by_method": {
            "ablation": abl[0] if abl else None,
            "shap": shp[0] if shp else None,
            "xgboost": xgb[0] if xgb else None,
        },
    }
