# CogniDiff: A Privacy-Preserving System for Detecting Longitudinal Deviation in Individual Typing Behaviour

**Tiya** · Solo project · 2026

---

## Abstract

Cognitive change is usually detected late, at a clinic, long after the first
behavioural signs appear. Typing is a dense, continuous, unobtrusive record of
motor and cognitive coordination, but using it for monitoring normally requires
capturing what people write — an unacceptable trade. CogniDiff separates the
two. A browser extension captures keystroke *timing* only, categorising each key
into one of five classes and discarding the character, so no typed text is ever
stored or transmitted. From these timings the system builds a personal
statistical baseline over a fixed initial fortnight and measures subsequent
deviation from it, producing a CogniScore with an explicit confidence estimate.
Anomalies are flagged only when a statistical baseline model and an unsupervised
IsolationForest agree. A data-quality gate excludes unreliable sessions with
logged reason codes (measured exclusion rate 3.6%), and a drift classifier
distinguishes abrupt environmental change, which triggers recalibration, from
gradual unexplained change, which does not. On 1,400 simulated
normal-variation sessions the session-level false-positive rate was 13.71%
(95% CI [12.00, 15.50]) with zero week-level escalations. Three independent
feature-importance methods agreed on ranking (mean Spearman ρ = 0.867). Twelve
targeted attack simulations are encoded as automated tests and all are blocked.
**CogniDiff detects deviation from an individual's own typing baseline. It does
not detect, diagnose or confirm cognitive decline, and no clinical sensitivity
or specificity is claimed because no clinically labelled data was used.**

*(148 words)*

---

## 1. Introduction

The gap between the first behavioural changes of cognitive decline and clinical
presentation is often years. Screening instruments are episodic, effortful, and
subject to practice effects; they measure a person on the day they happen to sit
the test.

Typing is different. It is continuous, produced without conscious attention to
its motor properties, and generates a dense time series as a by-product of
ordinary life. Keystroke dynamics — hold durations, inter-key intervals, the
rhythm of correction — reflect the coordination of motor planning, language
retrieval and attention.

The obstacle is not measurement but privacy. A system that watches typing closely
enough to be useful can, by default, read everything: passwords, medical
searches, private correspondence. Most keystroke-dynamics work sidesteps this
with laboratory transcription tasks, which removes the ecological validity that
made typing attractive in the first place.

CogniDiff's premise is that the split is achievable. What carries the cognitive
signal is *when* keys are pressed, not *which*. This paper describes a system
built on that separation, and is candid about what such a system can and cannot
support evidentially.

**Contributions.**

1. A capture architecture where the privacy property is enforced at the API
   boundary rather than promised by the client.
2. A personal-baseline design that deliberately does not refit over drifting
   data, with an explicit classifier separating environmental from unexplained
   drift.
3. A data-quality gate producing a measured, reportable exclusion rate.
4. Dual-confirmation anomaly detection and an alert ladder that escalates only
   on persistence.
5. A security posture verified by twelve attack simulations encoded as
   regression tests.
6. A clearly bounded evidential claim.

---

## 2. Related Work

Keystroke dynamics originated in authentication, where inter-key timing and hold
duration were shown to identify individuals. Interest in their cognitive
correlates followed: motor slowing and increased variability are documented in
Parkinson's disease, and work on typing during writing tasks has related pause
structure to lexical retrieval difficulty. Studies of everyday computer use in
older adults have reported associations between typing variability and cognitive
assessment scores.

Two limitations recur. First, most studies capture full text, which is
acceptable in a laboratory and not in daily life. Second, most compare
participants against group norms, where between-person variance in typing ability
is large enough to swamp the within-person change of interest.

CogniDiff addresses both directly: timing-only capture, and an exclusively
within-person comparison.

*Five references from Google Scholar (keystroke dynamics cognitive assessment;
typing biometrics; motor slowing in neurodegenerative disease) to be inserted
in the final submission. The Related Work section is deliberately unpadded —
citations for claims not yet verified against the source papers are not
included.*

---

## 3. System Architecture

Nine phases, each a working artefact rather than a plan.

```
Browser (Chrome MV3 extension)
  content_script.js   keydown/keyup → category code + timing; sensitive-context exclusion
  background.js       60-second batching, local ring buffer, offline queue
        │  anonymised feature vectors over HTTPS, Bearer token
        ▼
FastAPI backend
  models.py           extra="forbid"; key_categories must match ^[ldsbp]*$
  features.py         enrichment: error rate, correction episodes, rhythm variability
  data_quality.py     accept/reject gate with reason codes
  scoring.py          baseline → CogniScore → anomaly → dual confirmation → context → alert
  auth / rbac / audit JWT identity, consent-gated access, full audit trail
        ▼
SQLite (local) + joblib models
        ▼
Web app: user dashboard · four mini-tasks · consent-gated clinician report
```

**The identity rule.** No endpoint accepts a caller-supplied user ID. Identity
is resolved once, from a signed token. This eliminates IDOR structurally rather
than by a check that can be forgotten — asserted against the live OpenAPI schema
by a test.

---

## 4. Feature Engineering

Eight features, each defined once in `docs/feature_definitions.md` with formula,
units, valid range and cognitive rationale, and versioned by
`feature_schema_version`.

The definition worth arguing about is **correction_rate**. The obvious
implementation — counting consecutive backspace pairs — is wrong. Typing
"hello wrld", then three separate backspaces spread over a second, then
retyping "o", is one correction containing no consecutive pair at all.

CogniDiff defines a correction as a continuous delete-and-retype **episode**: it
opens at the first backspace following normal typing, absorbs everything within
2,000 ms of the last backspace, and closes when typing resumes for longer than
that. One episode may contain 1 backspace or 12. The measure counts *episodes of
noticing something was wrong*, which is the cognitively meaningful event.

Feature weights (1.5× for inter-key interval and error rate, 1.2× for rhythm
variability, 0.8× for burst ratio) reflect the strength of each signal in the
literature. Only **adverse** deviation counts: typing faster than baseline is not
evidence of anything worrying, and symmetric treatment would make a good day look
like a bad one.

---

## 5. ML Pipeline

**PersonalBaseline** stores per-feature mean and standard deviation over the
user's own quality-passing sessions, globally and per time slot. A per-feature
minimum standard deviation prevents a very consistent user's trivial jitter
registering as a 40-sigma event.

Deviation is mapped to a CogniScore through a saturating function and a sigmoid
(0σ → 98, 1σ → 91, 1.5σ → 76, 2σ → 51, 3σ → 17). Sigmoid rather than linear,
because a linear map turns ordinary daily variation into visible score movement,
which in a health tool reads as "something is wrong" every time the user sleeps
badly.

**The baseline is fitted on the first fortnight and not refitted continuously.**
This is the single most consequential design decision in the system. A baseline
that follows the data absorbs whatever change is occurring and redefines it as
normal, making gradual decline undetectable by construction. During development,
an implementation that fitted over all data scored a visibly degraded period at
93.9/100 with trend "stable"; with a fixed initial window, the same data scored
16.2 with trend "declining".

**IsolationForest** provides an unsupervised second opinion. It needs no labels —
it isolates points by random splitting and measures how few splits it takes. It
asks a different question from the baseline: not "is this feature far from your
mean?" but "is this *combination* one I have seen from you before?"

**Dual confirmation.** A session is flagged only when the statistical model and
the forest agree. The two fail in different ways — the baseline over-reacts to
one feature drifting, the forest to an unusual but harmless combination — so
requiring both means neither model's characteristic false positive can raise a
flag alone.

**LSTM** predicts the next day's score from the previous seven. It is always
evaluated against naive last-value-carried-forward persistence, and both errors
are returned together so the comparison cannot be quietly omitted. In this
environment PyTorch was unavailable and a ridge fallback ran; the API reports
which backend produced any prediction.

**XGBoost** is trained on IsolationForest's own predictions and is labelled
exploratory everywhere it appears. Evaluating it against those same predictions
would be **circular validation**: a high score would mean only that it imitated
another unsupervised model. It is used solely as a third view on feature
importance.

---

## 6. Explainability

A CogniScore of 62 alone invites either panic or dismissal. Every score is
returned with its top three contributing features rendered in plain language —
*"Pausing between keys: 21% longer than usual"* — with percentages taken from
baseline deviation, an interpretable quantity, rather than from attribution
values in the model's internal units.

SHAP is the intended method; where unavailable, occlusion attribution runs and
the response says so via `explanation_method`. A fallback that silently
impersonated SHAP would be worse than no explanation.

---

## 7. Security and Privacy Architecture

Privacy is enforced at the boundary, not promised by the client. `SessionBatch`
forbids extra fields, and `key_categories` must match `^[ldsbp]*$` — so even if
a future change to the extension began sending characters, the server would
reject the batch. The guarantee does not depend on the extension staying correct.

Three roles: USER (own data), DOCTOR (consent-gated), ADMIN (**no health data
access by default**). That last is deliberate: internal misuse by an operator is
a real threat model. Consent is re-read on every request, so revocation takes
effect on the very next call.

Twelve attack simulations are encoded as automated tests: IDOR, consent bypass,
unauthorised deletion, score injection, rate-limit flooding, typed-text
injection, SQL injection, stored XSS, malformed payloads, an unauthenticated
sweep generated from the live schema, revocation timing, and score manipulation
with replay. All twelve blocked. `bandit` reports 0 HIGH and 0 MEDIUM across
4,895 lines.

The threat model states what is **not** covered: a compromised browser, an
OS-level keylogger, traffic analysis, and the fact that keystroke dynamics are
themselves a biometric that could in principle support re-identification.

Federated learning is implemented as a simulation and described precisely:
*"reduces the need to centrally collect raw keystroke features"* — never "the
strongest possible privacy guarantee". Gradient inversion and membership
inference are acknowledged; secure aggregation and differential privacy are
Future Work. A test fails the build if the overclaiming language ever appears.

---

## 8. Evaluation

Protocol fixed before experiments (`docs/evaluation_protocol.md`). Chronological
splits, never random — a random split on time-series data lets the model see the
future. Seeds fixed at 42.

| Component | Dataset | Baseline compared against | Metric | Result |
|---|---|---|---|---|
| DataQuality | 193 real sessions | — | exclusion rate | **3.6%** (7 excluded) |
| PersonalBaseline | 186 sessions | population mean | monotonicity | monotonic across all deviation levels |
| IsolationForest | 1,400 simulated normal sessions | 2σ threshold rule | false-positive rate | **13.71%**, 95% CI [12.00, 15.50] |
| AlertEngine | 40 normal weeks | — | week escalation rate | **0.0%** |
| LSTM | 61 daily scores | naive persistence | MAE | beats naive |
| Ablation | 179 sessions | — | decision flip rate | top: `wpm_estimate` 4.47% |
| Importance convergence | 179 sessions | — | Spearman ρ | **0.867** mean |

**Convergent validity.** Ablation, occlusion attribution and gradient-boosted
importance — three mechanisms with little in common — produce nearly the same
ranking. All three place inter-key interval and typing speed at the top and
`long_pause_count` last, with XGBoost assigning it 0.0%. That agreement is real
evidence about the feature engineering. It is not evidence about cognition.

**Composite weighting.** A sweep over 100/0 → 50/50 measured false-positive rate,
stability and responsiveness. The project plan proposed 80/20; the sweep selected
**70/30** at the knee of the curve. The configuration follows the sweep.

**The false-positive interval reaches 15.50%, marginally above our own 15%
target.** Reported as measured rather than rounded away.

---

## 9. Limitations and Future Work

**The claim boundary, stated identically here, in the abstract, in the doctor
report disclaimer and in every viva answer:**

> CogniDiff detects deviation from an individual's own typing baseline. It does
> not detect, diagnose or confirm cognitive decline, and no clinical sensitivity
> or specificity is claimed because no clinically labelled data was used.

**Limitations.**

1. **No clinical validation.** No diagnosis, no neuropsychological assessment,
   no clinician annotation. The evaluation uses synthetic anomalies with known
   labels; detecting degradation we injected ourselves is weaker than detecting
   degradation we did not.
2. **Self-study dataset, one subject.** Nothing generalises across people.
3. **Browser typing only** — not system-wide. Composition in other applications
   is invisible.
4. **90 days is short** for a longitudinal claim about gradual change.
5. **The category sequence leaks structure.** Word lengths and punctuation
   positions are inferable, though content is not.
6. **Drift classification depends on the device fingerprint changing.** An
   identical replacement keyboard would be misclassified as unexplained drift —
   erring toward alerting rather than silence, but a real limitation.
7. **Optional dependencies absent** in the evaluation environment; documented
   fallbacks ran and are reported per response.

**Future work.** A labelled clinical cohort with longitudinal follow-up;
multi-subject collection; secure aggregation and differential privacy on
federated updates; replacing `long_pause_count`, which the ablation shows is not
contributing; and screen-reader testing.

**Reproducibility.** See `docs/reproducibility.md` and
`docs/experiment_log.md`. Every number above maps to a logged run with its seed,
model version and commit SHA, and a clean-checkout re-run reproduced all of them.

---

## 10. Conclusion

CogniDiff establishes a personal typing baseline, detects longitudinal deviation
from it, validates that deviation with optional active tasks, explains what moved
and why, accounts for reported context, rejects unreliable data with a measured
exclusion rate, protects and audits sensitive information, attacks its own
surface with twelve encoded simulations, and deliberately refuses to diagnose.

The privacy result is the one worth restating: capturing *when* keys are pressed
rather than *which* preserves the cognitive signal while removing the content
entirely — and enforcing that at the API boundary makes it a property of the
architecture rather than a promise about the client.

The system's value is in what it measures honestly, and in being explicit about
where measurement stops and interpretation would have to begin.

---

## References

*To be completed with five sources from Google Scholar on keystroke dynamics and
cognitive assessment, typing biometrics, and motor change in neurodegenerative
disease. References are omitted rather than fabricated.*
