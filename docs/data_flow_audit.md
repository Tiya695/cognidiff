# Keystroke Data Privacy Flow Audit

**Audited:** 2026-08-17 · CogniDiff v1.0
**Method:** manual trace of every step from source to storage, plus automated
assertions in `tests/test_security.py` and `tests/test_features.py`.

The question this document answers is narrow and answerable: **at each step in
the pipeline, what exactly exists in memory or on disk?**

---

## The trace

### 1. `keydown` in the browser

**Where:** `extension/content_script.js`

The raw `KeyboardEvent` exists here and nowhere else. `event.key` is read on
exactly one line, inside `categorise()`, and the character is discarded on the
next:

```js
function categorise(event) {
  const k = event.key;
  if (k === 'Backspace' || k === 'Delete') return 'b';
  ...
  if (k >= 'a' && k <= 'z') return 'l';
  ...
}
```

The function returns a single-character **category code**, never the character.
No variable anywhere in the file holds typed text.

| Question | Answer |
|---|---|
| Raw typed text held? | Only inside `categorise()`'s parameter, for one comparison |
| Individual key values retained? | **No** — the return value is `l`/`d`/`s`/`b`/`p` |
| Written to any variable outside the function? | **No** |

**Before this runs at all:** the sensitive-context check. Capture is abandoned
entirely — and the partial buffer *deleted*, not flushed — if the focused
element is a password field, has `autocomplete` containing `cc-` or
`one-time-code`, sits inside a form containing a password field, carries
`data-sensitive`, has a label matching `password|cvv|otp|pin|aadhaar|…`, or if
the URL matches the banking/payment/health/auth blocklist, or if the window is
incognito.

A batch that started on a normal page and continued into a checkout form never
leaves the browser.

---

### 2. Buffer → 60-second batch

**Where:** `content_script.js::buildBatch()`

Held in memory: an array of category codes, an array of millisecond offsets, an
array of key-hold durations. Aggregated into `wpm_estimate`,
`avg_inter_key_interval_ms`, `avg_hold_duration_ms`, `backspace_count`,
`total_keystrokes`, `pause_count`, `long_pause_count`.

| Question | Answer |
|---|---|
| Raw text stored? | **No** |
| Key values stored? | **No** |
| Feature vectors stored? | Yes — numbers and category codes only |

**Honest note on the category sequence.** We transmit the category string (e.g.
`"llslbll"`) because the server needs it for correction-event detection. This
reveals *word lengths and punctuation positions*, not characters. It is not
zero information and we do not claim it is: "hello world" and "abcde fghij"
produce an identical string. Recovering content from it is not possible;
inferring rough token structure is.

---

### 3. `background.js` → `chrome.storage.local`

Adds `date` (YYYY-MM-DD) and `hour` (0–23). Appends to a bounded ring buffer of
5,000 sessions. Nothing else is added.

The user can inspect this at any time (**View My Data**) and erase it
(**Delete All My Data**).

| Question | Answer |
|---|---|
| Raw text stored? | **No** |
| Stored where? | The user's own browser profile only |
| User-erasable? | Yes, one click, immediately |

---

### 4. `POST /api/session`

Sent over the wire: the feature batch, the category string, offset and interval
arrays, and a coarse device fingerprint. Authorised by a Bearer token.

The **device fingerprint** is deliberately blunt: `platform|screen-size-bucket|language`,
e.g. `Windows|md|en`. No hardware serial, no full user-agent, no resolution, no
canvas or font fingerprint. It exists only so the quality gate can tell that the
setup changed, and it is bucketed so it cannot single out a person.

**Enforced by `backend/models.py`:**

- `extra="forbid"` — a batch containing `raw_text` is rejected with 422.
- `key_categories` must match `^[ldsbp]*$` — **real characters are refused at the
  API boundary.** This is the structural guarantee: the privacy property does not
  depend on the extension continuing to behave.

---

### 5. `features.py::enrich_batch`

Computes `error_rate`, `correction_rate`, `correction_events`,
`rhythm_variability`, `long_pause_count`, `burst_ratio`, `time_slot`. Pure
arithmetic over timing arrays.

| Question | Answer |
|---|---|
| Raw text present? | **No** |
| Could text be reconstructed from the output? | No — the output is eight floats and a time-slot label |

---

### 6. SQLite `keystroke_sessions`

The category string and the offset/interval arrays are **not persisted**. They
are used for the quality gate and correction detection and then discarded. What
lands on disk is the numeric feature row plus `quality_score`, `excluded`,
`device_fingerprint`, `time_slot`, `date`, `hour`.

| Question | Answer |
|---|---|
| Raw typed text stored? | **No** |
| Individual key values stored? | **No** |
| Category sequence stored? | **No** — discarded after enrichment |
| Feature vectors stored? | Yes |
| Stored where? | `cognidiff.db`, local disk, in `.gitignore` |

---

### 7. ML models

`PersonalBaseline`, `IsolationForest`, `LSTM` and the exploratory XGBoost model
consume the numeric feature rows. The `.pkl` files contain means, standard
deviations and model parameters. No session content of any kind.

---

### 8. `/api/score` response

Returns the score, per-feature deviations, top-3 changes and alert status.
Feature *names* and percentages. No timing arrays, no category strings.

---

### 9. Claude API call — the only external transmission

**Where:** `backend/summary_generator.py`

Sent to Anthropic:

- the computed CogniScore (a number)
- three feature **labels** with percentage changes (e.g. "Pausing between keys: 21% longer than usual")
- a trend word (`declining` / `stable` / `improving`)
- a confidence band
- the user's first name, if they chose to enter one

Not sent: any keystroke data, any timing value, any raw feature, any user ID,
any session, any date.

Called at most once per user per day. All machine learning runs locally.

---

### 10. Dashboard render

Every value written with `textContent`. Verified by a grep test across all
frontend and extension JavaScript for `innerHTML`, `outerHTML`,
`insertAdjacentHTML` and `document.write` — currently zero hits.

---

## Automated verification

| Property | Test |
|---|---|
| A `raw_text` field is rejected | `test_attack_06_a_raw_text_field_is_rejected` |
| No text-shaped field is accepted | `test_attack_06b_no_text_shaped_field_is_accepted` |
| Real characters in `key_categories` are refused | `test_attack_06c_real_characters_in_key_categories_are_rejected` |
| Nothing resembling text reaches the database | `test_attack_06d_nothing_resembling_text_reaches_the_database` |
| Enrichment output carries no strings | `test_enrichment_never_carries_text` |
| The audit log never records health content | `test_the_audit_log_never_records_health_content` |
| No unsafe DOM writes anywhere | `test_attack_08b/08c` |

---

## Manual test log

| Scenario | Expected | Observed |
|---|---|---|
| Type in an `input[type=password]` | zero batches | zero batches, buffer discarded |
| Type on a URL matching `/checkout` | zero batches | zero batches |
| Type in an incognito window | zero batches | zero batches |
| Tab from a normal field into a password field mid-session | partial buffer deleted | deleted, `focusin` handler fired |
| Type normally on an allowlisted site | one batch per minute | batches with numbers only, no text in console |

---

## The privacy claim, phrased defensibly

**We write:**

> Because CogniDiff does not transmit or store raw typed content, a backend
> compromise should not expose the user's actual typed text.

**We do not write:**

> Even if the backend were compromised, no one could determine what the user
> actually typed.

The difference is not pedantry. The first states what the architecture
guarantees and is verifiable from this document. The second is an absolute claim
about an adversary's capabilities that we cannot support — and a reviewer who
notices the overreach will discount the rest of the work with it.

See `docs/privacy_architecture.md` for the threat model, including what this
design explicitly does **not** protect against.
