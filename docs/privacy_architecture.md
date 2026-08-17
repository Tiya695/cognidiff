# Privacy Architecture

**CogniDiff v1.0 · 2026-08-17**

Privacy here is not a feature that was added on top. It is the constraint the
rest of the system was built around: the decision not to read what people type
was made before any model existed, and every later design choice had to work
within it.

This document states what the architecture does, what it does not do, and — in
the threat model — what it explicitly cannot protect against. Companion
document: [`data_flow_audit.md`](data_flow_audit.md), which traces every piece
of data from source to storage.

---

## 1. What is captured

**Keystroke timing only. Never text.**

For each keystroke the browser records:

- a **category code** — one of `l` (letter), `d` (digit), `s` (space/enter/tab),
  `b` (backspace/delete), `p` (punctuation)
- a **timestamp offset** in milliseconds
- a **hold duration** — how long the key was down

`event.key` is read on exactly one line of `content_script.js`, inside
`categorise()`, and the character is discarded on the next. No variable in the
extension ever holds typed text.

**Capture never starts** when:

- the focused element is `input[type=password]`
- `autocomplete` contains `cc-`, `one-time-code`, `current-password` or `new-password`
- the element sits inside a form containing a password field
- the element carries `data-sensitive`, or a label matching
  `password|passcode|pin|cvv|cvc|otp|secret|token|ssn|aadhaar|card number|security code`
- the URL matches the banking / payment / health-portal / authentication blocklist
- the window is incognito

If a sensitive context appears **mid-session**, the partial buffer is **deleted**,
not flushed. A batch that started on a normal page and continued into a checkout
form never leaves the browser.

Monitoring runs only on sites the user has explicitly added to their allowlist,
and is **off by default** on install. Consent precedes capture.

---

## 2. What is stored locally in the extension

`chrome.storage.local` holds a bounded ring buffer of at most 5,000 anonymised
feature batches: numbers, category codes, a date and an hour. Nothing else.

The user can inspect this at any moment (**View My Data**) and erase it
(**Delete All My Data**). Both were built in Phase 1, before any ML existed —
data control is not an afterthought here, it is the first feature.

---

## 3. What is sent to the backend

Anonymised feature vectors, authorised by a Bearer token. The account identifier
is a random string (`u_` + 16 hex characters); it is not derived from a name or
an email, and neither is collected.

Also sent: a **coarse device fingerprint** — `platform|screen-size-bucket|language`,
e.g. `Windows|md|en`. No hardware serial, no full user-agent, no resolution, no
canvas or font fingerprint. It exists solely so the quality gate can detect that
the typing setup changed, and it is bucketed so it cannot single out a person.

**Enforced at the API boundary, in `backend/models.py`:**

- `extra="forbid"` on every request model — a batch containing `raw_text` is
  rejected with 422, never silently ignored.
- `key_categories` must match `^[ldsbp]*$` — real characters are refused.

That second rule is the structural core of the whole claim: **the privacy
property does not depend on the extension continuing to behave.** If a future
change to the content script started sending characters, the server would reject
the batch rather than store them.

The category sequence and timing arrays are used for correction-event detection
and the quality gate, then **discarded**. They are never persisted.

---

## 4. What is sent to the Claude API

The only external transmission in the system. At most once per user per day.

**Sent:** the computed CogniScore, three feature *labels* with percentage
changes ("Pausing between keys: 21% longer than usual"), a trend word, a
confidence band, and the first name the user chose to enter.

**Not sent:** any keystroke data, any timing value, any raw feature, any user ID,
any session, any date.

All machine learning runs locally at zero cost. Claude is the natural-language
communication layer, not the analysis layer.

---

## 5. Data retention

| Data | Retention |
|---|---|
| Raw feature rows (`keystroke_sessions`) | 90 days |
| CogniScores (`cogniscores`) | retained — small, and the trend is the point |
| Task results | 90 days |
| Audit log | 1 year (accountability record, contains no health content) |
| Encrypted backups | 7 daily + 4 weekly, then deleted |

---

## 6. User control

| Control | Where | Effect |
|---|---|---|
| Monitoring on/off | extension popup | immediate; content script detaches its listeners |
| Site allowlist | extension popup | capture only on chosen domains |
| View my data | popup + `/api/export/me` | full export, JSON |
| Delete local data | popup | clears `chrome.storage.local` |
| Delete everything | dashboard + `DELETE /api/user/me` | erases every row in every table, deletes all model files, invalidates the session |
| Grant doctor access | dashboard | explicit, per-clinician |
| Revoke access | dashboard | **effective on the clinician's very next request** |
| See who accessed my data | dashboard access log | every action, including denied attempts |

The full deletion path is verified by
`test_deletion_removes_rows_from_every_table_and_is_audited`.

---

## 7. Threat model

Being specific about what a design does *not* cover is what makes the rest of it
credible.

### Protected against

| Threat | Mitigation |
|---|---|
| **Backend compromise / database theft** | No raw typed content exists to steal. An attacker with the database file gets timing statistics, not text. |
| **IDOR — one user reading another's data** | No endpoint accepts a caller-supplied user ID. Identity comes only from a signed token. |
| **Internal misuse by an operator** | ADMIN has no access to health data by default. Doctor access requires an explicit, revocable, per-patient grant, and every access is logged. |
| **Clinician access after revocation** | Consent is re-read on every request. No cache, no grace period. |
| **Score forgery** | The CogniScore is derived server-side only; client-supplied score fields return 422. |
| **Credential and payment capture** | Capture is structurally disabled on password, payment and authentication contexts. |
| **Stored XSS** | Every rendered value uses `textContent`; enforced by a grep test. |
| **SQL injection** | Parameterised queries throughout; enforced by a grep test. |
| **API abuse / replay** | Rate limiting plus the quality gate. |
| **Backup loss or corruption** | Encrypted backups with a tested restore path. |
| **Secret compromise** | Token-version claim invalidates every issued token at once. |

### **Not** protected against

Stated plainly, because these sit outside CogniDiff's trust boundary and no
amount of design inside it changes that:

1. **A compromised browser.** If malware or a malicious extension is running in
   the user's browser, it can read what they type directly. CogniDiff's
   restraint is irrelevant to an attacker already inside the page.

2. **An OS-level keylogger.** Same reasoning, one layer down.

3. **A compromised user account.** Anyone holding the user's password and a
   valid token sees what the user sees.

4. **Traffic analysis.** An observer who can see *when* batches are sent learns
   when the user was typing, even without seeing the contents.

5. **Inference from the category sequence.** The category string reveals word
   lengths and punctuation positions. `hello world` and `abcde fghij` are
   identical to us, so content is not recoverable — but rough token structure is
   inferable, and we do not pretend otherwise.

6. **Re-identification from behavioural features.** Keystroke dynamics are
   themselves a biometric. A sufficiently rich feature history could plausibly
   be linked to an individual by an adversary holding another sample of their
   typing. This is a real limitation of the whole approach, not a bug in ours.

---

## 8. Federated learning — what it does and does not give us

`ml/federated.py` simulates federated training across three clients.

**The correct phrasing, reused verbatim in the paper and at viva:**

> Federated learning reduces the need to centrally collect raw keystroke
> features, because training can occur locally and only model updates are
> aggregated.

**Never:** "the strongest possible privacy guarantee."

Federated learning is **not** automatic privacy. Model updates can leak
information about the data they were trained on — gradient inversion and
membership inference attacks are well documented in the literature and are not
defeated by federation alone. Secure aggregation and differential-privacy noise
on updates are the mitigations, and they belong in Future Work, not in our
claims.

This is asserted by `test_the_limitation_is_stated_and_never_overclaims`, which
fails the build if the phrase "guarantees privacy" or "strongest possible" ever
appears in that module's stated limitation.

---

## 9. How the privacy claim is phrased

**We write:**

> Because CogniDiff does not transmit or store raw typed content, a backend
> compromise should not expose the user's actual typed text.

**We do not write:**

> Even if the backend were compromised, no one could determine what the user
> actually typed.

The first states what the architecture guarantees and is verifiable from the
data flow audit. The second is an absolute claim about an adversary's
capabilities that we cannot support — and a reviewer who spots the overreach
will, quite reasonably, discount everything else with it.

Claim what the architecture does. Never claim what an attacker could never
achieve.
