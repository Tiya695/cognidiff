# Attacker Simulation — Twelve Targeted Attacks

**System:** CogniDiff v1.0
**Run date:** 2026-08-17
**Method:** every attack is encoded as an automated test in `tests/test_security.py`
and runs on every `pytest` invocation.

Running an attack once by hand proves nothing about tomorrow's code. Encoded as
tests, a regression that reopens a closed hole fails the suite immediately
instead of waiting to be rediscovered — by us, or by somebody else.

```bash
python -m pytest tests/test_security.py -v
```

---

## Result summary

| # | Attack | Expected | Result | Test |
|---|--------|----------|--------|------|
| 1 | IDOR — read another user's dashboard | 401/403 | **BLOCKED** | `test_attack_01*` |
| 2 | Doctor report without consent | 403 | **BLOCKED** | `test_attack_02*` |
| 3 | Unauthorised deletion | 401/403 | **BLOCKED** | `test_attack_03*` |
| 4 | Fake CogniScore via implausible features | rejected/excluded | **BLOCKED** | `test_attack_04*` |
| 5 | Rate-limit flood | 429 | **BLOCKED** | `test_attack_05*` |
| 6 | Typed-text injection | 422 | **BLOCKED** | `test_attack_06*` |
| 7 | SQL injection | 422 or inert literal | **BLOCKED** | `test_attack_07*` |
| 8 | Stored XSS | renders as characters | **BLOCKED** | `test_attack_08*` |
| 9 | Malformed / oversized payloads | 422 or 413, never 500 | **BLOCKED** | `test_attack_09*` |
| 10 | Unauthenticated sweep of every endpoint | 401 everywhere | **BLOCKED** | `test_attack_10*` |
| 11 | Consent revocation timing | 403 on the very next request | **BLOCKED** | `test_attack_11*` |
| 12 | Score manipulation and replay | 422 + server-computed score stands | **BLOCKED** | `test_attack_12*` |

**12 / 12 BLOCKED.** No unresolved findings.

---

## Attack 1 — Insecure Direct Object Reference

**What was tried.** Sign in as User A and request User B's dashboard by
manipulating the request: changing a URL parameter, tampering with the token,
and forging an unsigned `alg: none` token carrying `role: ADMIN`.

**Request**
```http
GET /api/dashboard/me
Authorization: Bearer <token for user A, with a hand-built payload claiming user B>
```

**Response.** `401 Unauthorized`.

**Why it is blocked.** Structurally, rather than by a check that could be
forgotten. There is no `/api/dashboard/{user_id}` route to attack — the test
asserts against the OpenAPI schema that **no endpoint anywhere takes a caller's
own user_id as a parameter**. Identity is resolved in exactly one place,
`get_current_user`, from a signed token. Before this change the API trusted a
URL segment; afterwards there is no URL segment to trust.

The forged-token variants fail signature verification: the fallback JWT
implementation compares with `hmac.compare_digest` and the `alg: none` header is
never honoured because the signature is recomputed with HS256 regardless of
what the header claims.

---

## Attack 2 — Doctor report without consent

**What was tried.** A DOCTOR account requests a patient report with no consent
grant; then, separately, probes for valid user IDs by comparing error messages.

**Response.** `403 Forbidden` in both cases, **with identical response bodies**.

**Why it is blocked.** `require_self_or_consenting_doctor` re-reads
`consent_grants` on every request. Nothing is cached.

The equal-error detail matters as much as the refusal: returning "no such user"
for one ID and "no consent" for another would turn the endpoint into a user
enumeration oracle. Both paths return the same sentence.

The denial is written to the audit log, so the patient can see that someone
tried.

---

## Attack 3 — Unauthorised deletion

**What was tried.** `DELETE /api/user/me` with no token; then with a valid token
belonging to a different user.

**Response.** `401` with no token. With another user's token the request
succeeds — but deletes **that** caller's data, not the target's, because there
is no target parameter. Verified: after User B deletes, User A's four sessions
are still present.

---

## Attack 4 — Fake CogniScore via implausible features

**What was tried.** A batch engineered to look perfect: minimal keystrokes, ideal
timings, every feature pinned at baseline. Then out-of-range values (`wpm = 5000`)
and impossible internal contradictions (`backspace_count > total_keystrokes`).

**Response.** The engineered-perfect batch is stored but marked
`excluded = 1` with reason `LOW_VOLUME`, so it cannot reach any model. The
out-of-range and contradictory batches return `422`.

**Note.** The `backspace_count > total_keystrokes` check exposed a real bug
during development: it was written as a Pydantic *field* validator, and Pydantic
validates fields in declaration order — `backspace_count` is declared first, so
the check compared against a value that was not populated yet and passed
everything. It is now a `model_validator(mode="after")`. The test caught this;
manual testing had not.

---

## Attack 5 — Rate limiting

**What was tried.** 20 × `POST /api/session` as fast as possible; 20 failed
logins against a known username.

**Response.** `429 Too Many Requests` with a `Retry-After` header after the 5th
session (limit 5/minute) and the 10th login attempt (limit 10 per 5 minutes per IP).

Limits live in one place, `backend/ratelimit.py::LIMITS`, so the documentation
and the tests quote the same numbers.

---

## Attack 6 — Typed-text injection

**What was tried.** `POST /api/session` carrying `raw_text`, then `typed_text`,
`content`, `keystrokes_raw`, `keys`; then real characters smuggled through the
legitimate `key_categories` field.

**Response.** `422` every time.

**Why it is blocked.** Two independent mechanisms:

1. `model_config = ConfigDict(extra="forbid")` on every request model. An unknown
   field is rejected, never silently dropped — a silently ignored field is one
   somebody will eventually find a way to make count.
2. `key_categories` is validated against `^[ldsbp]*$`. This is the structural
   guarantee behind the whole privacy claim: **even if a future change to the
   content script started sending real characters, the API would refuse the
   batch rather than store them.** The promise does not depend on the extension
   staying correct.

---

## Attack 7 — SQL injection

**What was tried.** `' OR '1'='1`, `'; DROP TABLE keystroke_sessions;--`,
`admin'--`, and a `UNION SELECT` against the login endpoint and the consent
endpoint.

**Response.** `401` or `422`. Afterwards, every table still exists and every row
is intact.

**Why it is blocked.** Every query uses parameterised placeholders. A third test
greps `backend/` and `ml/` for SQL built by f-string, `%` or concatenation and
fails if it finds any — so the property is *checked mechanically* rather than
asserted from memory.

That grep caught one instance during development: `delete_user_data` looped over
table names with an f-string. The names were constants and it was safe, but a
codebase where "we only interpolate the safe ones" is true is a codebase where
the rule cannot be enforced automatically. It is now six literal statements.

---

## Attack 8 — Stored XSS

**What was tried.** `<script>alert(document.cookie)</script>` submitted through
every free-text field, then the dashboard and doctor report loaded.

**Response.** The text renders as visible characters. No alert box. No execution.

**Why it is blocked.** Every value from the API is written with `textContent`.
A test greps all frontend and extension JavaScript for `innerHTML`, `outerHTML`,
`insertAdjacentHTML` and `document.write` and fails on any hit — currently zero
across the whole codebase.

---

## Attack 9 — Malformed and oversized payloads

**What was tried.** A 10 MB body; `total_keystrokes = 999999999`; negative
`wpm_estimate`; a string where a number belongs; `hour = 99`; a malformed date;
a null body.

**Response.** `413` for the oversized body (rejected by middleware before it is
parsed), `422` for everything else. **Never a 500, never a crash.**

Error bodies were checked for information leakage: no tracebacks, no SQL text,
no absolute paths, no `site-packages`. Unhandled exceptions return a generic
message plus a request ID; the full traceback is logged server-side only.

---

## Attack 10 — Unauthenticated sweep

**What was tried.** Every endpoint in the OpenAPI schema called with no
`Authorization` header at all. This is the test that catches the endpoint
somebody forgot to protect.

**Response.** `401` from every endpoint except the four intentionally public
ones: `/api/health`, `/api/auth/login`, `/api/auth/register`,
`/api/federated/status`.

The public endpoints were separately checked for leakage — `/api/health` returns
version metadata and no usernames, IDs, secrets or tokens.

Because the sweep is generated *from the live schema*, a newly added endpoint is
covered the moment it exists. There is no list to keep in sync.

---

## Attack 11 — Consent revocation timing

The full lifecycle as a single test:

1. User grants doctor access → **200**, report loads.
2. User clicks revoke.
3. Doctor immediately retries with the **same still-valid JWT** → **403**.

No cached response. No grace period. Revocation that only takes effect at the
next login is a grace period with better manners, and it is a real
vulnerability — the window is exactly as long as the token's remaining life.

The audit log was verified to contain all four events: the grant, the successful
access, the revocation, and the denied attempt. A revoked doctor also disappears
from `/api/doctor/patients` immediately.

---

## Attack 12 — Score manipulation

**What was tried.** `POST /api/score` with `raw_score = 100`; `POST /api/session`
with `cogni_score = 95` and `anomaly = false`; crafted payloads containing
`adjusted_score`, `is_anomaly`, `alert_status` and `confidence`. Then the same
valid batch replayed 50 times to inflate the daily average.

**Response.** `422 extra-fields-forbidden` on every forged field. The stored
score is still the one the server computed from the stored features. The replay
is stopped at the 5th submission by the rate limiter.

**Why it is blocked.** The CogniScore is derived entirely server-side in
`backend/scoring.py`. `ScoreRequest` carries a single boolean and nothing else.
Only `_persist()` writes to the `cogniscores` table, and a test asserts against
the OpenAPI schema that **no PUT or PATCH route to a score exists at all**.

At viva: *a client can send behavioural features, never a score.*

---

## Additional hardening verified

Beyond the twelve, the suite also asserts:

- Security headers present on every response (`nosniff`, `DENY`, `no-referrer`, `no-store`).
- Login gives one identical message for "no such user" and "wrong password" — no enumeration oracle.
- Passwords never returned and never stored in the clear.
- **ADMIN has no access to health data**, by design. An admin can manage accounts and read the audit log; the health endpoints refuse them exactly as they refuse a stranger. Internal misuse is a real threat model, not a hypothetical one.
- `ADMIN` cannot be self-registered — it is provisioned out of band.
- Bumping `token_version` invalidates every issued token at once (incident response step 3).
- Deletion removes rows from every table and writes an audit entry.
- The audit log never contains health content — checked by grepping stored `details` for feature names and score fields.

---

## Re-run policy

New code creates new attack surface. The full simulation runs:

- on every `pytest` invocation, so effectively on every change;
- again after any major feature addition;
- before every release tag.

| Run | Date | Result |
|-----|------|--------|
| Initial | 2026-08-17 | 12/12 BLOCKED |
| Post Phase 7 | 2026-08-17 | 12/12 BLOCKED |
| Post Phase 8 | 2026-08-17 | 12/12 BLOCKED |
