# Ground Truth Strategy

This is the document that protects the project in viva. It states exactly what
kind of labels CogniDiff has, what it therefore measures, and — most importantly
— what it does **not** claim.

---

## The three label layers

### 1. REAL DATA — no cognitive labels

Actual keystroke sessions collected from real typing through the browser
extension.

- **Used for:** behavioural monitoring, personal baseline modelling, drift
  detection, the data quality statistics.
- **Labels available:** none. Nobody has told us which of these sessions were
  "cognitively off", and there is no way to find out retrospectively.
- **What it can support:** claims about a person's typing deviating from their
  own established pattern.

### 2. SYNTHETIC ANOMALIES — known labels, artificial

Sessions deliberately degraded by a documented amount: slower typing, longer
inter-key intervals, elevated error rate, less steady rhythm.

- **Used for:** controlled evaluation of the detector only — precision, recall,
  false-positive rate, ablation.
- **Labels available:** exact, by construction.
- **What it can support:** claims about whether the detector detects the kind of
  degradation we injected.
- **What it cannot support:** anything about whether that degradation resembles
  real cognitive change. We chose the degradation; finding it again is not
  evidence about the world.

### 3. CLINICAL LABELS — not available

- No diagnosis.
- No neuropsychological assessment.
- No clinician annotation.
- No longitudinal outcome data.

**This layer does not exist in this project, and no result presented anywhere in
it depends on pretending otherwise.**

---

## The claim boundary

One sentence, repeated **identically** in the paper abstract, the limitations
section, the doctor report disclaimer, the API description and every viva answer:

> **CogniDiff detects deviation from an individual's own typing baseline. It
> does not detect, diagnose or confirm cognitive decline, and no clinical
> sensitivity or specificity is claimed because no clinically labelled data was
> used.**

Everything reported is a statement about *behavioural deviation*. Nothing
reported is a statement about *cognition*.

---

## What each number in this project actually means

| Reported number | What it means | What it does **not** mean |
|---|---|---|
| CogniScore | Distance from this person's own typing baseline | A cognitive test score |
| False-positive rate 13.7% | How often normal variation is flagged as behavioural anomaly | A clinical false-positive rate |
| Ablation ranking | Which features drive the detector's decisions | Which features indicate cognitive decline |
| Feature importance ρ = 0.867 | Three methods agree on what the model relies on | Three methods agree about cognition |
| Alert `PERSISTENT_DEVIATION` | A behavioural pattern persisted across days | A finding, a diagnosis, or a prediction |
| LSTM prediction | Extrapolation of the recent score sequence | A prognosis |

---

## The hard question, rehearsed

> **"How do you know your model is actually detecting Alzheimer's?"**

> **"It is not, and we never claim it is. We evaluate detection of behavioural
> deviation against synthetic anomalies with known labels. Establishing a link
> to clinical cognitive decline would require a labelled clinical cohort and a
> longitudinal study, which is stated as future work."**

Say it plainly and without hedging. Conceding this confidently is far stronger
than an impressive-sounding claim that collapses under one follow-up question —
and an examiner who knows the field will ask that follow-up.

### Related questions and their honest answers

**"Then what is the point of the system?"**
Detecting *change from an individual's own baseline* is a genuinely useful
screening signal, and it is the step that has to come before any clinical
question can be asked. CogniDiff is positioned as a monitoring and screening
tool that tells a person "something about your typing has shifted and persisted"
— which is actionable as a prompt to seek an opinion, and is not a diagnosis.

**"Why not just get clinical labels?"**
That requires a clinical cohort, ethics approval, longitudinal follow-up and
neuropsychological assessment. It is the correct next step and it is what Future
Work describes. It is not something that can be improvised, and improvising it
would be worse than not having it.

**"Isn't the XGBoost model validated?"**
No, and it is labelled as exploratory everywhere it appears. It is trained on
IsolationForest's own predictions, so evaluating it against those predictions is
**circular validation** — a high score means only that XGBoost successfully
imitated another unsupervised model. It is used for one legitimate purpose: a
second, independent view on feature importance.

**"Your false-positive rate is on synthetic data — does it mean anything?"**
It means the detector does not fire on *the kind of normal variation we
modelled*: variable typing speed, stress-inflated error rates, tiredness. It is
a lower bound on robustness, not a clinical operating characteristic, and it is
reported with a bootstrap confidence interval rather than as a point estimate.

---

## Why this framing is a strength

A project that overclaims gets dismantled in ten minutes. A project that states
its evidential limits precisely, and then reports solid results *within* those
limits, is doing recognisable science.

CogniDiff's real contributions are architectural and methodological — a personal
baseline that is deliberately not refitted over drifting data, a quality gate
with a measured exclusion rate, dual-confirmation anomaly detection, environmental
versus unexplained drift classification, a security posture verified by twelve
encoded attacks, and a privacy design that makes the central claim structurally
enforceable rather than a promise.

None of those depend on a clinical claim, and none of them are weakened by
declining to make one.
