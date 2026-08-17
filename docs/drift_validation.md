# Drift Validation

The single most important distinction in CogniDiff, and the one that separates a
monitoring tool from a false-alarm generator in one direction and from a tool
that detects nothing in the other.

Implementation: `ml/drift_detector.py`. Tests: `tests/test_baseline.py`.

---

## The two cases

### ABRUPT_ENVIRONMENTAL

A new keyboard, a different laptop, a changed layout or language. The shift is
**sudden**, has a **known external cause**, and says nothing about the person.

**Response:** suspend judgement. Set `baseline_status = RECALIBRATING`, suppress
every alert, mark scores provisional, generate no doctor report, collect 30
quality-passing sessions on the new setup, then refit automatically and return to
`ACTIVE`.

### GRADUAL_UNEXPLAINED

A slow shift with **no environmental cause**. This is precisely the signal
CogniDiff exists to detect.

**Response:** leave the baseline alone. Keep alerting. Do **not** recalibrate.

---

## Why getting this backwards fails in both directions

Recalibrate on a gradual unexplained shift and the system can never detect
gradual decline, because it redefines each week's decline as the new normal. It
would run forever and find nothing, by construction.

Fail to recalibrate on a device change and every new keyboard reads as cognitive
decline, and the user learns to ignore the tool.

This is also why the baseline is fitted on the **first** two weeks and not
continuously refitted — see `backend/config.py::BASELINE_WINDOW_DAYS`. A baseline
that follows the data cannot measure movement away from itself.

---

## How the two are told apart

`classify_drift()` checks, in order:

1. **Device fingerprint change.** If the fingerprint changes between consecutive
   sessions, measure the mean absolute feature step across that boundary. A
   fingerprint change *plus* a simultaneous step is `ABRUPT_ENVIRONMENTAL`, with
   confidence `high` when the step exceeds 1σ.

2. **Rolling-mean slope.** With no fingerprint change, fit a least-squares slope
   to the 7-day rolling mean of adverse deviation. A sustained slope
   (>0.02σ per session) spanning at least 14 days is `GRADUAL_UNEXPLAINED`.

3. Otherwise `STABLE`.

The order matters: an environmental explanation, where one exists, is checked
before a cognitive one is inferred.

---

## Test 1 — device change mid-series

**Setup.** 10 sessions on `Windows|md|en`, then 10 on `Darwin|lg|en` with
elevated inter-key interval, rhythm variability and error rate — a plausible
new-keyboard signature.

**Result:**

```
classification      ABRUPT_ENVIRONMENTAL
recommended_action  recalibrate
confidence          high
```

**End-to-end via the API:**

| Step | Expected | Observed |
|---|---|---|
| Report `device_changed: true` | status → RECALIBRATING | RECALIBRATING |
| Dashboard alert | RECALIBRATING, provisional | RECALIBRATING, `provisional: true` |
| Alert raised | none | none |
| Banner shown | recalibration notice with progress | *"Recalibrating to your new setup — scores are provisional and no alerts will be raised until your new baseline is established. 0 of 30 clean sessions collected."* |
| Doctor report | not generated | not generated |

Tests: `test_a_device_change_classifies_as_environmental`,
`test_reporting_a_device_change_starts_recalibration`,
`test_recalibrating_suppresses_every_alert`.

---

## Test 2 — gradual shift, no device change

**Setup.** 40 sessions over 40 days, same device throughout, with a steady creep:
typing speed 60 → 48 wpm, inter-key interval 180 → 250 ms, error rate
0.04 → 0.09, rhythm variability 90 → 160.

**Result:**

```
classification      GRADUAL_UNEXPLAINED
recommended_action  alert_and_keep_baseline
confidence          moderate
```

| Step | Expected | Observed |
|---|---|---|
| Baseline status | stays ACTIVE | ACTIVE |
| Baseline refitted | **no** | no |
| Alerts suppressed | **no** | no — the alert engine still escalates |
| Dashboard banner | flags an unexplained shift | *"A steady shift with no device or environment change to explain it. This is not recalibrated away — it is exactly what CogniDiff watches for."* |

Test: `test_a_gradual_shift_with_no_cause_is_never_recalibrated_away`.

**If this test ever starts returning `ABRUPT_ENVIRONMENTAL`, the tool has quietly
become a false-alarm suppressor.** That is why it is a permanent regression test
rather than a one-off check.

---

## Test 3 — feature drift detection

**Setup.** 14 sessions with consistently elevated error rate (0.16 versus a 0.04
baseline), inter-key interval 290 ms and rhythm variability 200.

**Result:** `drift_severity` medium/high, with `error_rate` among the drifted
features at >2σ. Stable data returns `none`/`low`.

Tests: `test_a_sustained_shift_is_detected`, `test_stable_data_shows_no_drift`.

---

## Recalibration window

| Property | Value |
|---|---|
| Sessions required | 30 quality-passing on the new device |
| Alerts during window | suppressed entirely |
| Scores during window | shown, marked **provisional** |
| Doctor report | not generated |
| Trend claims | not made |
| On completion | automatic refit, status → ACTIVE, `baseline_version` bumped |

Progress is surfaced to the user, not hidden: *"12 of 30 clean sessions
collected."* A silent recalibration window would leave someone wondering why
their score stopped meaning anything.

---

## Known limitation

Classification depends on the device fingerprint changing. A user who buys an
*identical* replacement keyboard produces no fingerprint change, so a genuine
environmental shift would be classified `GRADUAL_UNEXPLAINED`.

The mitigation is the manual control: the context form's **"New keyboard or
device"** checkbox triggers recalibration directly, without waiting for the
fingerprint to disagree. It is documented on the dashboard for exactly this case.

The residual risk is a user who changes hardware, does not tell us, and whose new
hardware fingerprints identically. That would produce a false `GRADUAL_UNEXPLAINED`
— which errs toward alerting rather than toward silence. In a screening tool
that is the safer direction, but it is a real limitation and it is stated in the
paper.
