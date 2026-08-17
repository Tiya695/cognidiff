# False-Positive Validation

**Run:** 2026-08-17 · seed 42 · `python -m ml.false_positive_test`

The question: if a cognitively normal person has a variable week — slept badly,
stressed, rushing, a couple of genuinely scrappy sessions — how often does
CogniDiff wrongly call it anomalous?

In a health tool this number matters more than sensitivity. A false alarm costs
a real person real anxiety about their own mind, and a tool that cries wolf gets
switched off long before it ever catches anything.

---

## Design

- A settled baseline fortnight (40 sessions) fitted normally.
- **40 simulated weeks**, 7 days each, 5 sessions per day = **1,400 sessions**.
- **No cognitive decline in any of them.** Every session is drawn from the same
  distribution as the baseline.
- Realistic non-cognitive variation layered on:
  - per-day variability multiplier drawn from 0.7× to 1.9×, so some days are
    simply scrappier than others
  - on 35% of days, error rate inflated by up to 50% to stand in for stress and
    tiredness
- Every session run through PersonalBaseline → IsolationForest →
  dual confirmation → AlertEngine.

---

## Results

| Metric | Result |
|---|---|
| Sessions simulated | 1,400 |
| **Session-level false-positive rate** | **13.71%** |
| **95% bootstrap CI** | **[12.00%, 15.50%]** |
| **Week-level escalation rate** | **0.0%** |
| Mean CogniScore | 94.29 |
| Target | below 15% |
| **Outcome** | **PASS** |

### Thresholds that produced these numbers

| Parameter | Value |
|---|---|
| Deviation threshold | 25% |
| IsolationForest contamination | 0.08 |
| Dual confirmation | both models must agree before a flag |
| Day counts as anomalous | when **most** of its sessions were flagged |
| Week escalation counted | only `SIGNIFICANT_DEVIATION` or above |

---

## Reading the two rates

**Session-level 13.71%** is the rate at which one individual minute of typing
gets flagged. It is under the 15% target, but the confidence interval reaches
**15.50%** — marginally above it. That is stated rather than rounded away. A
single point estimate would have read as a comfortable pass; the interval says
the true rate could sit slightly over the line.

**Week-level 0.0%** is the number that actually reaches the user. Zero of 40
normal weeks escalated to `SIGNIFICANT_DEVIATION` or above.

The gap between the two is the whole design. Individual sessions are noisy and
CogniDiff expects them to be. The alert ladder requires *persistence across
days* before it says anything, so a 13.7% per-session flag rate produces no user-
facing alarms at all on normal variation.

### Two design decisions this measurement forced

Both were changed because the first version of this test produced numbers that
looked wrong:

1. **A day is anomalous when most of its sessions are flagged, not when any one
   is.** With five sessions a day and a 13.7% per-session rate, "any" marks
   about half of all days as anomalous — enough for ordinary noise to walk up
   the alert ladder on its own. One distracted minute out of five is a
   distracted minute.

2. **`MONITOR` is not counted as a false alarm.** It is by design a soft state —
   *"a few sessions this week looked different from your baseline. This is
   within the range of normal variation — we are keeping an eye on it."* It
   raises nothing, recommends nothing, and generates no report. Counting it as
   an alarm would be counting the system saying "this is normal" as the system
   crying wolf. Under the first measurement it gave an 87.5% week rate, which
   said more about the metric than the system.

---

## Limitations

1. **Synthetic normal data.** Real normal variation may be wider, or wider in
   different directions, than the model here.
2. **Single simulated subject** with one baseline. Between-person variation is
   not represented at all.
3. **No true positives measured.** This test measures only the false-positive
   side. Sensitivity would require the labelled clinical cohort described in
   [`ground_truth_strategy.md`](ground_truth_strategy.md) — without it, a very
   low false-positive rate could equally mean the detector never fires, so this
   number should be read alongside the ablation results, which show the detector
   does respond to injected degradation.
4. **The CI upper bound exceeds the target.** 15.50% versus a 15% goal. Reported
   as measured.

---

## If the rate needs lowering

In order of preference:

1. Raise the deviation threshold above 25% — the bluntest lever, and it costs
   sensitivity directly.
2. Lower `contamination` below 0.08 — makes the forest more conservative.
3. Require three consecutive anomalous days rather than a count within seven.
4. Weight context adjustment more heavily when the user reports poor sleep or
   high stress.

Option 3 is the most attractive: it targets persistence, which is the property
the alert ladder already relies on, rather than desensitising the detector
itself.
