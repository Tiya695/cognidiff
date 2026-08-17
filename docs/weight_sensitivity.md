# Composite Weight Sensitivity Sweep

**Run:** 2026-08-17 · seed 42 · `python -m ml.weight_sensitivity`

When the examiner asks *"why exactly 80 and 20?"*, the answer has to be a table,
not a preference. So we swept it — and the sweep did not pick 80/20.

---

## The sweep

Six weightings between passive keystroke monitoring and the active mini-tasks,
measured on three things that trade off against each other:

- **False-positive rate** — how often known-normal days fall below the flag threshold
- **Stability** — std dev of the daily composite across a stable week (lower is better; a metric that jitters is unreadable)
- **Responsiveness** — how far the score drops on deliberately degraded days (higher is better; a metric that never moves is useless)

| Weighting | FP % | Stability (σ) | Responsiveness | Resp / σ |
|---|---|---|---|---|
| 100/0 | 0.00 | 5.009 | 19.25 | 3.843 |
| 90/10 | 0.00 | 4.698 | 19.59 | 4.171 |
| 80/20 | 0.25 | 4.457 | 19.94 | 4.475 |
| **70/30** | **0.25** | **4.296** | **20.29** | **4.723** ← chosen |
| 60/40 | 0.50 | 4.226 | 20.64 | 4.884 |
| 50/50 | 0.75 | 4.251 | 20.99 | 4.938 ← peak |

---

## Chosen: 70/30

**Not** the raw maximum. 50/50 has the highest responsiveness-per-unit-instability
(4.938), but the curve is flat near the top: past 70/30, each further step buys
about 2% more responsiveness while the false-positive rate keeps climbing —
tripling from 0.25% to 0.75% between 70/30 and 50/50.

So the selection rule is a **knee rule**: take the *smallest* task weight that
gets within 5% of the best ratio. 70/30 reaches 4.723, which is 95.6% of the
peak, at a third of the peak's false-positive rate.

**The tie-break direction is deliberate.** Keystroke monitoring is passive and
always running; the mini-tasks depend on the user choosing to sit down and do
them. When two weightings perform equivalently, the one that leans on the
channel which is actually there is the more robust choice.

`backend/config.py` is set to `KEYSTROKE_WEIGHT = 0.70`, `TASK_WEIGHT = 0.30`.

---

## Two modelling decisions that changed the answer

Both were added after a first version of the sweep produced a result that said
more about the simulation than about CogniDiff. Recording them matters, because
each one moved the conclusion.

### 1. The task channel must carry independent signal

The first sweep modelled the mini-tasks as a noisier measurement of the *same*
thing keystrokes measure. Under that model the answer was trivially **100/0** —
if one channel is a noisier copy of another, never use it.

But that is not why the tasks exist. Passive monitoring catches gradual change;
the active tasks catch **acute** change, the kind that shows up in a single
afternoon. The sweep now models `ACUTE_ONLY_FRACTION = 0.35` of degraded days as
visible in the tasks while the day's typing still looks ordinary.

### 2. The task channel is usually absent

With independent signal added, the sweep swung to **50/50** — because nothing
represented the cost of leaning on an optional input.

The mini-tasks are user-initiated and mostly skipped. `scoring.py::_composite`
falls back to keystroke-only when there are no task results for the day. So the
heavier the task weight, the further a task day sits from a non-task day, and the
score jumps for reasons that have nothing to do with the person.

The sweep now models `TASK_COMPLETION_RATE = 0.30` on normal, stable **and**
degraded days. Applying it only to normal days would have handed the task channel
a benefit it does not have in practice — the tasks are not magically present on
exactly the days that matter.

With both terms in, stability has a genuine interior minimum at 60/40, and the
knee rule lands on 70/30.

---

## Assumptions, stated plainly

The conclusion is **conditional** on two parameters that are estimates, not
measurements:

| Parameter | Value | Basis |
|---|---|---|
| `ACUTE_ONLY_FRACTION` | 0.35 | assumed — no data on how much acute change escapes passive monitoring |
| `TASK_COMPLETION_RATE` | 0.30 | assumed, deliberately pessimistic — optional self-assessment in a long-running health tool is skipped far more often than it is done |

A real deployment should re-run this sweep against **observed** task-completion
rates. If users complete tasks far more often than 30%, the knee moves toward a
heavier task weight; if they complete them rarely, it moves the other way.

This is the honest form of the result: the method is sound and reproducible, the
inputs are declared, and the conclusion is stated as conditional on them.

---

## Departure from the project plan

The plan proposed 80/20. The sweep was run as specified and preferred **70/30**.
The configuration follows the sweep.

That is what running the experiment is for. If the number had been chosen first
and the sweep run to confirm it, the sweep would have been decoration.
