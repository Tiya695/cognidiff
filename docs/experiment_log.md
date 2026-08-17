# Experiment Log

One row per run. Every number in the research paper is traceable to a row here.
When an examiner asks where a figure came from, you point at the row.

**Environment for all runs:** Python 3.14.3 · Windows 11 · seed 42 · commit `b09eeb6`
Packages: `requirements.lock` (73 pinned).

---

| ID | Timestamp | Script | Seed | Model version | Dataset window | Key parameters | Result | Commit |
|---|---|---|---|---|---|---|---|---|
| **E-01** | 2026-08-17 14:52 | `scripts/make_icons.py` | — | — | — | sizes 16/48/128 | 3 PNG icons written | `b09eeb6` |
| **E-02** | 2026-08-17 16:05 | `backend/seed_demo.py --days 75 --reset` | 42 | — | 2026-06-04 → 2026-08-17 | drift 0.38, 5 slots/day | 193 sessions, 186 accepted, 7 excluded (3.6%) | `b09eeb6` |
| **E-03** | 2026-08-17 16:06 | `scoring.fit_lstm` | 42 | `lstm_h32_v1` | 61 daily scores | seq_len 7, ridge fallback | `beats_naive: true` | `b09eeb6` |
| **E-04** | 2026-08-17 16:38 | `ml/weight_sensitivity.py` | 42 | — | 400 synthetic days | acute-only 0.35, task completion 0.30, knee tol 0.05 | **chosen 70/30**; peak 50/50 at ratio 4.938; 70/30 at 4.723, FP 0.25% | `b09eeb6` |
| **E-05** | 2026-08-17 16:40 | `ml/false_positive_test.py` | 42 | `isolationforest_v1` | 40 weeks × 7 days × 5 sessions = 1,400 | contamination 0.08, deviation threshold 25% | **FP 13.71%**, 95% CI [12.00, 15.50]; week escalation **0.0%**; mean score 94.29 | `b09eeb6` |
| **E-06** | 2026-08-17 16:52 | `ml/ablation.py` + `compare_methods` | 42 | `isolationforest_v1` | 179 quality sessions | leave-one-out, 5 features | Top: `wpm_estimate` (4.47% flip). Mean Spearman ρ **0.867** across ablation / occlusion / XGBoost | `b09eeb6` |
| **E-07** | 2026-08-17 16:20 | `GET /api/sessions/quality` | — | — | full demo dataset | threshold 60 | 193 total, 186 analysed, 7 excluded, **3.6%**; reasons LOW_VOLUME, SHORT_DURATION, INCOMPLETE_CAPTURE | `b09eeb6` |
| **E-08** | 2026-08-17 17:04 | `ml/federated.py` | 42 | logistic FedAvg | 3 clients × 120 synthetic sessions | 3 rounds, lr 0.2, 40 local epochs | 3 rounds; loss 0.130 → 0.071 → 0.049; accuracy 1.00 **(see caveat)**; `raw_features_transmitted: false` | `b09eeb6` |
| **E-09** | 2026-08-17 17:20 | `pytest tests/test_security.py` | 42 | — | — | 12 attacks + hardening checks | **63 passed** — 12/12 BLOCKED | `b09eeb6` |
| **E-10** | 2026-08-17 16:30 | `bandit -r backend/ ml/` | — | — | 4,895 LOC | default profile | **0 HIGH, 0 MEDIUM**, 11 LOW (all reviewed and accepted) | `b09eeb6` |
| **E-11** | 2026-08-17 17:45 | in-browser accessibility audit | — | — | 4 pages, 443 elements | WCAG 2.1 AA, alpha-composited | **0 contrast failures**, worst 5.21:1, min text 10.5px | `b09eeb6` |
| **E-12** | 2026-08-17 16:19 | `backend/backup.py verify` | — | — | live database | Fernet, 7 daily + 4 weekly | restore verified, all 7 table counts match, 234.8 KB | `b09eeb6` |
| **E-13** | 2026-08-17 17:30 | `pytest tests/ -q` | 42 | — | — | full suite | **187 passed** | `b09eeb6` |
| **E-14** | 2026-08-17 15:10 | `pytest --cov=backend --cov=ml` | 42 | — | — | coverage | 67% overall; scoring and security paths 78–100% | `b09eeb6` |
| **E-15** | 2026-08-17 16:28 | `pip-audit` | — | — | 73 packages | — | 1 finding: `ecdsa` 0.19.2 PYSEC-2026-1325 — accepted, documented, not reachable (HS256 only) | `b09eeb6` |

---

## Caveat on E-08 — the federated accuracy of 1.00 means nothing

The simulation reports perfect accuracy after one round. That is **not** a
result about CogniDiff; it is a property of the synthetic data. The "anomalous"
clients' sessions are drawn from a distribution displaced far enough from normal
that a logistic model separates them trivially.

What E-08 legitimately demonstrates is **mechanical**: that FedAvg runs, that
loss decreases monotonically as client updates are aggregated, that the
simulation is reproducible, and that no raw feature ever leaves a client. Those
are the claims made in the paper.

Reporting 1.00 as evidence of detection quality would be exactly the kind of
number that collapses under one follow-up question. It is recorded here so the
figure is never quoted without its caveat.

---

## Runs that changed a decision

Recording the runs that *changed our minds* matters more than recording the ones
that confirmed what we already thought.

### E-04a → E-04 · the weight sweep was rewritten twice

**E-04a (first attempt).** Modelled the mini-tasks as a noisier measurement of
the same thing keystrokes measure. Result: **100/0** — "never use the tasks".
That was a finding about the simulation, not about CogniDiff: if one channel is
a noisier copy of another, of course you discard it. Added
`ACUTE_ONLY_FRACTION = 0.35` so the task channel carries signal the passive
channel cannot see.

**E-04b (second attempt).** Result swung to **50/50**, because nothing
represented the cost of leaning on an input the user usually skips. Added
`TASK_COMPLETION_RATE = 0.30`, applied to normal, stable *and* degraded days.

**E-04 (final).** Stability gained a genuine interior minimum, and the knee rule
selected **70/30** — not the 80/20 the project plan proposed. The configuration
follows the sweep. That is the whole point of running it.

### E-05a → E-05 · the false-positive metric was wrong twice

**E-05a.** Week-level escalation came back at **87.5%**, which would have meant
the alert engine was unusable. Two measurement errors: a day was marked
anomalous if *any* one of its five sessions was flagged, and `MONITOR` — a state
whose own message says "this is within the range of normal variation" — was
being counted as a false alarm.

**E-05.** Day requires a majority of sessions flagged; only `SIGNIFICANT` and
above counts as an alarm. Result: **0.0%**. The session-level rate (13.71%) was
unchanged by either fix — it was the aggregation that was wrong, not the
detector.

### Baseline window · a silent methodological error

The first implementation fitted the baseline on **all** available sessions. On
the demo dataset this scored a visibly degraded final fortnight at **93.9/100**
with trend "stable" — the baseline had absorbed the very drift it was supposed
to measure. Fixed by fitting on the **first** 14 days only
(`BASELINE_WINDOW_DAYS`), after which the same data scored 16.2 with trend
"declining".

A baseline that follows the data cannot measure movement away from itself. This
is now `docs/drift_validation.md`'s central point and is covered by
`test_a_gradual_shift_with_no_cause_is_never_recalibrated_away`.

### CogniScore calibration

With the corrected baseline, the original sigmoid (centre 38, slope 0.11) mapped
the demo's degraded period to **0.1/100**. Statistically defensible — it really
was several sigma out — and useless as a user-facing number.

Recalibrated to a saturating deviation map plus a gentler sigmoid (centre 58,
slope 0.07), giving: 0σ → 98, 1σ → 91, 1.5σ → 76, 2σ → 51, 3σ → 17. Monotonicity
is enforced by `test_the_score_is_monotonic_in_deviation`.

---

## Bugs found by the test suite, not by hand

| Bug | Found by | Impact if shipped |
|---|---|---|
| `backspace_count > total_keystrokes` never rejected — field validator read a field Pydantic had not populated yet | `test_attack_04c` | contradictory payloads accepted |
| `latest_session` ordered only by `created_at`; same-second inserts tie and SQLite returns an arbitrary row | `test_task_scores_blend_into_the_composite` | an offline-queue flush could masquerade as today's reading |
| f-string SQL in `delete_user_data` | `test_attack_07c` | not exploitable, but unenforceable as a rule |
| 37 contrast failures at 3.11:1 | accessibility audit | unreadable labels for the intended user group |
