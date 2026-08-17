# Feature Definitions

**Feature schema version: `v1`** — declared in `backend/config.py::VERSIONS`.

Every feature CogniDiff computes is defined here exactly once: formula, units,
valid range, and the cognitive behaviour it is meant to capture. At viva the
answer to "how exactly is that computed" has to be one precise sentence, not a
gesture at the code.

**If any definition on this page changes, `feature_schema_version` must be
bumped.** Scores computed under different schema versions are not comparable,
and every stored score carries the schema version that produced it precisely so
that a later change cannot silently invalidate earlier data.

Implementation: `backend/features.py`. Unit tests: `tests/test_features.py`.

---

## Captured in the browser

These arrive from the extension. They are computed from event timings, never
from key values.

### `wpm_estimate`
- **Formula:** `(total_keystrokes / 5) / elapsed_minutes`
- **Units:** words per minute
- **Range:** 0–300 (rejected outside)
- **Captures:** gross typing throughput. The `/5` is the standard convention
  that five keystrokes make one word.

### `avg_inter_key_interval_ms` → stored as `avg_iki_ms`
- **Formula:** arithmetic mean of the gaps between consecutive `keydown` events
- **Units:** milliseconds
- **Range:** 0–30,000
- **Captures:** the pause between one keystroke and the next. **The single most
  important quantity in this project.** A consistently longer inter-key interval
  means more time is being spent between keys — retrieving the next word,
  planning the next character, recovering attention. Because it is measured
  against the person's own baseline, it is not confounded by whether they are a
  naturally fast or slow typist.

### `avg_hold_duration_ms` → stored as `avg_hold_ms`
- **Formula:** mean of `keyup − keydown` per key, discarding holds ≥ 5,000 ms
- **Units:** milliseconds
- **Range:** 0–5,000
- **Captures:** motor execution rather than cognition. Useful mainly as a
  control: if hold time moves but inter-key interval does not, the change is
  more likely physical than cognitive.

### `backspace_count`, `total_keystrokes`, `pause_count`
- **Units:** counts within the 60-second window
- **`pause_count`:** gaps longer than **2,000 ms**

---

## Computed server-side

### `error_rate`
- **Formula:** `backspace_count / total_keystrokes`
- **Range:** 0.0–1.0
- **Captures:** how much of the typing was deletion. Rises with typos,
  hesitation and self-correction.

### `correction_events` and `correction_rate`

The definition that matters most, because the obvious one is wrong.

**Not used:** counting consecutive backspace pairs. Typing `hello wrld`, then
three separate backspaces spread over a second, then retyping `o`, is **one**
correction — but it contains no consecutive backspace pair at all, so the naive
measure scores it zero.

**Used — the episode definition.** A correction event is one continuous
delete-and-retype episode:

1. it **starts** at the first backspace that follows a non-backspace keystroke;
2. it **absorbs** every backspace and every keystroke occurring within
   **2,000 ms** of the last backspace;
3. it **ends** when normal typing resumes for longer than 2,000 ms.

One event may contain 1 backspace or 12.

A batch that *opens* on a backspace does not start an event — that deletion
continues typing from a window we did not capture, so it is not evidence of a
correction in this batch.

- **`correction_rate`** = `correction_events / total_keystrokes`, range 0.0–1.0
- Also computed: `mean_keystrokes_deleted_per_event`, `mean_correction_duration_ms`
- **Captures:** how often the writer noticed something was wrong and went back.
  Counts *episodes of noticing*, not keypresses.

### `rhythm_variability`
- **Formula:** population standard deviation of inter-key intervals, discarding
  values outside (0 ms, 30,000 ms)
- **Units:** milliseconds
- **Range:** 0 to unbounded; typical 40–200
- **Captures:** how *even* the typing is. Low variability means an automatic,
  practised rhythm. High variability means typing that starts and stops —
  hesitation, word-finding, divided attention. It is the feature most sensitive
  to *how* text is produced rather than how fast, which is why it carries a
  1.2× weight.

### `long_pause_count`
- **Formula:** count of inter-key intervals > **3,000 ms**
- **Captures:** distinct stops, as opposed to general slowing.

### `burst_ratio`
- **Formula:** `count(intervals < 150 ms) / count(intervals)`
- **Range:** 0.0–1.0
- **Captures:** the proportion of keystrokes produced inside fluent bursts —
  chunks arriving as practised motor sequences rather than one deliberate key at
  a time. The noisiest feature in the set, so it carries a 0.8× weight.

### `time_slot`
- **Formula:** from `hour` — `morning` 05:00–11:59, `afternoon` 12:00–16:59,
  `evening` 17:00–21:59, `night` 22:00–04:59
- **Captures:** time of day. Baselines are also fitted per slot, because a
  person's 2am typing is not comparable to their 10am typing.

### `device_fingerprint`
- **Formula:** `platform | screen-width-bucket | language`, e.g. `Windows|md|en`
- **Deliberately blunt.** No hardware serial, no full user-agent, no resolution,
  no canvas or font fingerprinting. It exists only so the quality gate can see
  that the setup changed, and it is bucketed so it cannot single out a person.

---

## Feature weights

Applied when combining per-feature deviations into the CogniScore
(`backend/config.py::FEATURE_WEIGHTS`):

| Feature | Weight | Why |
|---|---|---|
| `avg_iki_ms` | **1.5** | strongest cognitive signal in the keystroke-dynamics literature |
| `error_rate` | **1.5** | strongest cognitive signal |
| `rhythm_variability` | **1.2** | sensitive to production, not just speed |
| `wpm_estimate` | 1.0 | gross but confounded by task and mood |
| `avg_hold_ms` | 1.0 | more motor than cognitive |
| `correction_rate` | 1.0 | informative but correlated with error rate |
| `long_pause_count` | 1.0 | informative but sparse |
| `burst_ratio` | **0.8** | noisiest, damped |

Only **adverse** movement counts toward deviation. Typing *faster* than baseline
is not evidence of anything worrying, and treating deviation symmetrically would
make a good day look like a bad one.

---

## Directionality

Which direction of movement counts as adverse (`ml/baseline.py::HIGHER_IS_WORSE`):

| Feature | Higher is worse? |
|---|---|
| `avg_iki_ms`, `avg_hold_ms`, `error_rate`, `correction_rate`, `rhythm_variability`, `long_pause_count` | yes |
| `wpm_estimate`, `burst_ratio` | no — lower is worse |

---

## Minimum standard deviations

`ml/baseline.py::MIN_STD` puts a floor under each feature's baseline standard
deviation. Without it, a user who happens to be extremely consistent would have
a near-zero denominator, and trivial jitter would register as a 40-sigma event.
Tested by `test_a_constant_feature_does_not_explode`.

| Feature | Floor |
|---|---|
| `wpm_estimate` | 1.5 |
| `avg_iki_ms` | 8.0 |
| `avg_hold_ms` | 3.0 |
| `error_rate` | 0.005 |
| `correction_rate` | 0.003 |
| `rhythm_variability` | 5.0 |
| `long_pause_count` | 0.4 |
| `burst_ratio` | 0.01 |
