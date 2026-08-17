# Security Incident Response

A short numbered procedure, not a framework. It has to be usable at 2am by
someone who is worried.

**Dry-run completed:** 2026-08-17 · duration 18 minutes · scenario: "Attack 12
succeeded — a client was able to write its own CogniScore."

---

## Procedure

### 1. Detect and record the time of discovery

Write down, immediately: what was seen, where, and the wall-clock time. Do not
start fixing yet. The timestamp bounds the exposure window later, and it is the
one thing that becomes impossible to reconstruct once you start changing things.

### 2. Disable the affected endpoint or feature

```bash
# in .env
MAINTENANCE_MODE=true
```

Data endpoints return **503**; the audit log stays writable so the response
itself is recorded. Restart the API to apply.

For a single endpoint, comment out the route and redeploy — faster than a full
maintenance window if the blast radius is known.

### 3. Rotate all secrets and invalidate every issued token

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"                      # SECRET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # BACKUP_KEY
```

Rotate `ANTHROPIC_API_KEY` from console.anthropic.com.

Then invalidate every token already in the wild:

```python
from backend import database as db
db.execute("UPDATE users SET token_version = token_version + 1")
```

Every JWT carries a `tv` claim checked against the user's current
`token_version` on every request, so this takes effect immediately rather than
waiting for tokens to expire. Verified by
`test_token_version_bump_invalidates_every_issued_token`.

**Rotating `BACKUP_KEY` makes existing backups undecryptable.** Restore-verify
the most recent backup with the old key and re-encrypt before discarding it.

### 4. Preserve evidence before any fix

```bash
sqlite3 cognidiff.db ".mode csv" ".once incident_audit_$(date +%Y%m%d).csv" \
  "SELECT * FROM security_audit_log ORDER BY id"
python -m backend.backup create
```

Export read-only, and take a backup of the current state **before** patching.
A fix that also destroys the evidence of what happened leaves you unable to
answer the only question that matters afterwards: what was reached, and by whom.

### 5. Patch, and add a regression test that reproduces the vulnerability

The test comes first. Write a test that fails against the current code and
demonstrates the hole, then fix until it passes. Add it to
`tests/test_security.py` next to the attack it belongs to.

A fix without a test is a fix that will be undone by someone who did not know it
was load-bearing.

### 6. Re-run the full twelve-attack simulation

```bash
python -m pytest tests/test_security.py -v
python -m pytest tests/ -q
python -m bandit -r backend/ ml/
python -m pip_audit
```

All twelve must show BLOCKED before maintenance mode comes off. Record the run
date in `attacker_simulation_results.md`.

### 7. Notify affected users, and record the notification

Tell them: what was exposed, when, for how long, what has been done, and what
they should do. Plainly, without minimising.

Record the notification in the audit log:

```python
from backend import audit
audit.log_action(
    actor_id="system", actor_role="ADMIN",
    action="INCIDENT_NOTIFICATION",
    resource="incident/<id>", outcome=audit.OUTCOME_SUCCESS,
    details={"users_notified": n, "incident": "<short reference>"},
)
```

Health data reaches a threshold where notification is an obligation rather than
a courtesy. When it is genuinely unclear whether an incident qualifies, notify.

---

## Operational hooks this procedure depends on

Both were built and tested before the dry-run, because a procedure that depends
on capabilities you have never exercised is a wish list.

| Hook | Where | Test |
|---|---|---|
| Token-version invalidation | `auth.py::bump_token_version` | `test_token_version_bump_invalidates_every_issued_token` |
| Maintenance mode | `main.py::security_middleware` | manual — 503 from data endpoints, audit log writable |
| Encrypted backup + restore | `backend/backup.py` | `python -m backend.backup verify` |
| Audit log export | `security_audit_log` table | manual |

---

## Dry-run record

**Date:** 2026-08-17 · **Scenario:** Attack 12 succeeded — a crafted payload set
`raw_score = 100` and the value was persisted.

| Step | Action | Time |
|---|---|---|
| 1 | Recorded discovery time and the offending request | 2 min |
| 2 | `MAINTENANCE_MODE=true`, restarted, confirmed 503 | 3 min |
| 3 | Rotated `SECRET_KEY` and `BACKUP_KEY`, bumped all `token_version` | 4 min |
| 4 | Exported the audit log, took a backup | 2 min |
| 5 | Wrote a failing test, then the `extra="forbid"` fix | 5 min |
| 6 | Re-ran the suite — 12/12 BLOCKED | 2 min |
| 7 | Drafted the notification text | — |
| | **Total** | **18 min** |

### What the dry-run exposed

1. **Rotating `BACKUP_KEY` orphans existing backups.** Not obvious until you do
   it. Step 3 now says so explicitly.
2. **Maintenance mode needs a restart** to pick up the `.env` change. Fine for a
   single instance; a multi-instance deployment would want a live flag.
3. **The evidence export was almost done after the fix**, which would have
   captured a database already modified by the patch. Step 4 now sits before
   step 5 for that reason.

Finding these in a dry-run rather than during a real incident is the entire
point of dry-running it.
