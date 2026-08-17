# Ablation Study and Feature Importance Convergence

**Run:** 2026-08-17 · seed 42 · 179 quality-passing sessions
**Method:** `ml/ablation.py` — leave-one-feature-out, refit the IsolationForest,
measure how many anomaly verdicts flip.

Reproduce:

```bash
python -c "from backend import database as db; from ml.ablation import run_ablation; \
import json; u=db.get_user_by_username('tiya'); \
print(json.dumps(run_ablation(db.good_sessions(u['id'])), indent=2))"
```

---

## Ablation results

| Rank | Feature | Decision flip rate | Anomaly count change |
|---|---|---|---|
| 1 | `wpm_estimate` | **4.47%** | 0.00% |
| 2 | `avg_iki_ms` | **3.35%** | 0.00% |
| 3 | `error_rate` | 2.23% | 0.00% |
| 4 | `rhythm_variability` | 1.12% | 0.00% |
| 5 | `long_pause_count` | 1.12% | 0.00% |

**Reading it.** The flip rate is the proportion of sessions whose normal/anomalous
verdict changes when the feature is withheld. Removing `wpm_estimate` changes
4.47% of decisions; removing `long_pause_count` changes 1.12%. The detector
leans hardest on the two features that describe *speed and spacing*.

The anomaly count change is 0.00% throughout — the *number* of flagged sessions
stays constant even as *which* sessions get flagged changes. That is worth
noticing rather than glossing over: it is a property of IsolationForest's fixed
`contamination` parameter, which pins the expected outlier proportion. So the
count is uninformative here by construction, and the flip rate is the metric
that carries information. Reporting the count alone would have looked like "no
feature matters", which would have been wrong.

---

## Convergent validity — three independent methods

| Method | 1st | 2nd | 3rd | 4th | 5th |
|---|---|---|---|---|---|
| **Ablation** (leave-one-out) | wpm_estimate | avg_iki_ms | error_rate | rhythm_variability | long_pause_count |
| **Occlusion attribution** (SHAP fallback) | wpm_estimate | avg_iki_ms | rhythm_variability | error_rate | long_pause_count |
| **XGBoost** (pseudo-label) | avg_iki_ms | wpm_estimate | error_rate | rhythm_variability | long_pause_count |

XGBoost importance shares:

| Feature | Importance |
|---|---|
| `avg_iki_ms` | 45.3% |
| `wpm_estimate` | 26.4% |
| `error_rate` | 15.0% |
| `rhythm_variability` | 13.2% |
| `long_pause_count` | **0.0%** |

### Rank agreement (Spearman ρ)

| Pair | ρ |
|---|---|
| Ablation vs occlusion | **0.90** |
| Ablation vs XGBoost | **0.90** |
| Occlusion vs XGBoost | **0.80** |
| **Mean** | **0.867** |

**Strong convergent validity.** Three methods that work by entirely different
mechanisms — retraining without a feature, perturbing a single input, and
gradient-boosted split gain — produce nearly the same ordering.

---

## What this does and does not establish

**Establishes:** the timing features carry the signal. `avg_iki_ms` and
`wpm_estimate` occupy the top two positions in all three rankings.
`long_pause_count` is last in all three, and XGBoost assigns it exactly 0.0%
importance. That convergence is real evidence about the feature engineering, and
it is the kind of evidence a single method cannot provide.

**Does not establish:** anything about cognition. All three methods are
measuring what *this detector* relies on, and the detector was fitted on
unlabelled data. Agreement between three views of the same model is not
agreement about the world. See
[`ground_truth_strategy.md`](ground_truth_strategy.md).

---

## Two honest caveats

1. **The XGBoost ranking comes from pseudo-labels.** It was trained on
   IsolationForest's own predictions, so its "agreement" with the ablation is
   partly agreement with itself — both derive from the same underlying forest.
   Occlusion vs ablation is the more independent of the three comparisons, and
   it is also the pair with the highest agreement.

2. **The SHAP result is from the occlusion fallback.** The `shap` package is not
   installed in this environment, so `CogniExplainer` used occlusion
   attribution: reset one feature to its baseline mean, re-score, attribute the
   change. Less principled than Shapley values — occlusion ignores feature
   interactions, which Shapley values are specifically designed to handle. The
   API reports `explanation_method: "occlusion"` rather than implying SHAP ran.

---

## Practical consequence

`long_pause_count` earns its place least. It is retained because it is cheap,
interpretable, and clinically plausible as a hesitation marker — but a future
version should either drop it or replace it with something that measures pause
*structure* rather than pause count. The ablation says the current form is not
contributing.

That is the sort of conclusion an ablation study exists to produce: a specific,
actionable statement about one feature, backed by a number.
