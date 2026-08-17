# Model Evaluation Protocol

**Filled in BEFORE running the experiments**, so the metrics were not chosen
after seeing which ones looked best. Seeds fixed at 42
(`backend/config.py::set_all_seeds`).

Read alongside [`ground_truth_strategy.md`](ground_truth_strategy.md), which
bounds what any of these numbers are allowed to mean.

---

## Splitting rule

**Chronological, never random.** The data is a time series. A random split lets
the model train on Thursday and test on Wednesday — it has seen the future, and
every metric comes back inflated.

- First **60%** of sessions → training
- Next **20%** → validation and threshold tuning
- Final **20%** → held-out test, touched exactly once

All random seeds fixed and recorded. Every run is listed in
[`experiment_log.md`](experiment_log.md).

---

## Per-component protocol and results

### PersonalBaseline

| | |
|---|---|
| **Dataset** | 186 real sessions, self-collected, 2026-06-04 → 2026-08-17 |
| **Split** | first 14 days fitted as baseline; remainder evaluated against it |
| **Baseline compared against** | a global (population) mean over the same features |
| **Metric** | deviation accuracy — does a known-degraded session score lower than a known-normal one |
| **Expected** | monotonic: worse deviation never produces a higher score |
| **Actual** | monotonic across all tested deviation levels (`test_the_score_is_monotonic_in_deviation`) |
| **Note** | the personal baseline separates degraded from normal sessions that a population mean does not, because the population mean is dominated by between-person variance |

### IsolationForest anomaly detector

| | |
|---|---|
| **Dataset** | quality-passing sessions + synthetic controlled anomalies |
| **Split** | chronological; detector fitted on the same first-14-day window as the baseline |
| **Baseline compared against** | a simple 2-sigma threshold rule on `avg_iki_ms` |
| **Metric** | precision, recall, F1 on synthetic anomalies; false-positive rate on normal variation |
| **Expected** | FP rate below 15% on normal variation |
| **Actual** | **13.71%** session-level FP rate, 95% CI **[12.00, 15.50]** |
| **Contamination** | 0.08 |

### LSTM trend model

| | |
|---|---|
| **Dataset** | 61 daily mean CogniScores |
| **Split** | chronological, 7-day sliding window |
| **Baseline compared against** | **naive last-value-carried-forward persistence** |
| **Metric** | MAE and RMSE on next-day score |
| **Expected** | beat naive persistence, or report honestly that it does not |
| **Actual** | beats naive on the demo series (`beats_naive: true`) |
| **Backend** | `ridge_fallback` — PyTorch is optional and not installed in this environment; the module reports which backend ran rather than implying an LSTM was used |

**This is the honest-reporting case the protocol was written for.** If the
trend model cannot beat carrying yesterday's value forward, that is a real
finding and gets reported as one. `evaluate()` always returns both the model's
error and the naive baseline's error side by side, so the comparison cannot be
quietly omitted.

### AlertEngine

| | |
|---|---|
| **Dataset** | 40 simulated variable-but-normal weeks (1,400 sessions) |
| **Metric** | proportion of normal weeks escalating to SIGNIFICANT or above |
| **Expected** | low single figures |
| **Actual** | **0.0%** |
| **Note** | MONITOR is explicitly a soft state — "within the range of normal variation" — and raises nothing with the user, so it is not counted as a false alarm |

### CogniScore

| | |
|---|---|
| **Metric** | test–retest stability across a stable week |
| **Expected** | small day-to-day movement on unchanged behaviour |
| **Actual** | mean 94.29 across 1,400 normal-variation sessions; stability std 4.30 at the chosen weighting |
| **Calibration** | 0σ → 98, 1σ → 91, 1.5σ → 76, 2σ → 51, 3σ → 17 |

### SHAP / explanation consistency

| | |
|---|---|
| **Metric** | is the top feature stable across reruns with the same input, and does it agree with the ablation ranking |
| **Expected** | stable and broadly agreeing |
| **Actual** | deterministic across reruns; Spearman ρ = **0.90** with the ablation ranking |
| **Method** | `occlusion` — `shap` is optional and not installed here; the API reports which method ran rather than implying SHAP |

### Feature importance convergence

Three independent methods, ranked on the same 179 sessions:

| Method | 1st | 2nd | 3rd | 4th | 5th |
|---|---|---|---|---|---|
| Ablation (leave-one-out) | wpm_estimate | avg_iki_ms | error_rate | rhythm_variability | long_pause_count |
| Occlusion attribution | wpm_estimate | avg_iki_ms | rhythm_variability | error_rate | long_pause_count |
| XGBoost (pseudo-label) | avg_iki_ms | wpm_estimate | error_rate | rhythm_variability | long_pause_count |

| Pair | Spearman ρ |
|---|---|
| Ablation vs occlusion | 0.90 |
| Ablation vs XGBoost | 0.90 |
| Occlusion vs XGBoost | 0.80 |
| **Mean** | **0.867** |

**Interpretation.** Strong convergent validity. Three methods that work by
different mechanisms agree that timing features — inter-key interval and typing
speed — carry the signal, and that `long_pause_count` contributes least. All
three place it last, and XGBoost assigns it 0.0% importance.

That agreement is real evidence about the feature engineering. It is **not**
evidence about cognition — see the claim boundary.

---

## Confidence intervals

Every rate that gets quoted is bootstrapped: resample the session set 1,000
times, report the 2.5th and 97.5th percentiles.

| Quantity | Estimate | 95% CI |
|---|---|---|
| Session false-positive rate | 13.71% | [12.00, 15.50] |

A single point estimate from one small self-collected dataset is not evidence.
The interval is the honest version of the number — and note that the upper bound
here reaches 15.5%, marginally above our own 15% target. That is stated rather
than rounded away.

---

## Data quality statistics

| | |
|---|---|
| Total sessions | 193 |
| Analysed | 186 |
| Excluded on quality | 7 |
| **Exclusion rate** | **3.6%** |
| Reason breakdown | `LOW_VOLUME`, `SHORT_DURATION`, `INCOMPLETE_CAPTURE` |

Every exclusion is logged with a reason code in `session_exclusions`, so this is
a measured number rather than an estimate.

---

## Known limitations of this protocol

1. **Single subject.** All real data comes from one person. Nothing here
   generalises across people, and no between-subject claim is made.
2. **Synthetic anomalies are our own construction.** Detecting degradation we
   injected ourselves is a weaker result than detecting degradation we did not.
3. **No clinical labels**, so no clinical operating characteristics.
4. **The 90-day window is short** for a longitudinal claim about gradual change.
5. **PyTorch and SHAP are not installed** in the evaluation environment, so the
   trend and explanation results come from the documented fallbacks. Both report
   which backend ran; neither pretends to be the other.
