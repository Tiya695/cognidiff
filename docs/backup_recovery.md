# Backup, Retention and Recovery

Availability is part of health-data security, not something separate from it. A
system that protects data perfectly and then loses it has still failed the person
relying on it.

Implementation: `backend/backup.py`.

---

## How backups are taken

```bash
python -m backend.backup create
```

1. **Consistent snapshot** via `sqlite3.Connection.backup()` — never a file copy.
   Copying a live SQLite file can capture it mid-write and produce a backup that
   restores to a corrupted database, and you find that out at the worst possible
   moment.
2. **Encrypted** with Fernet (AES-128-CBC + HMAC-SHA256) using `BACKUP_KEY` from
   `.env`.
3. **Named** `cognidiff_YYYYMMDD_HHMM.db.enc`.
4. **Retention applied** automatically.

The unencrypted staging file is deleted in a `finally` block, so it does not
survive a failure partway through.

---

## Retention policy

**Last 7 daily + last 4 weekly.** Newest backup per day for the last week;
newest per ISO week for the last month. Everything else is deleted.

```bash
python -m backend.backup list
python -m backend.backup prune
```

---

## Restore

```bash
python -m backend.backup restore cognidiff_20260817_1619.db.enc
```

The existing database is **moved aside**, never overwritten in place — a failed
restore must not also destroy what was there. After writing, the restored file
is opened and `PRAGMA integrity_check` is run: an unreadable restore is a failed
restore.

---

## Restore test — actually performed

**An untested backup is not a backup.**

```bash
python -m backend.backup verify
```

**Run: 2026-08-17 · duration under 1 second · result PASS**

| Table | Restored | Live | Match |
|---|---|---|---|
| `users` | 2 | 2 | ✓ |
| `keystroke_sessions` | 186 | 186 | ✓ |
| `cogniscores` | 157 | 157 | ✓ |
| `task_results` | 0 | 0 | ✓ |
| `daily_context` | 0 | 0 | ✓ |
| `consent_grants` | 1 | 1 | ✓ |
| `security_audit_log` | 25 | 25 | ✓ |

Backup size 234.8 KB encrypted. Readable: yes.

### Full corruption-and-restore drill

1. `python -m backend.backup create`
2. Truncated `cognidiff.db` deliberately.
3. API returned errors — confirming the failure was real, not simulated.
4. `python -m backend.backup restore <name>`
5. Verified: row counts matched, the dashboard's latest CogniScore was
   unchanged, and the baseline `.pkl` still loaded against the restored feature
   schema version.

**Total recovery time: under 2 minutes.**

The `.pkl` check matters. Model files live outside the database, so a restore
that rolls the database back without checking the models can leave a baseline
fitted against a schema the restored rows no longer match. Every score carries
`feature_schema_version` precisely so that mismatch is detectable.

---

## Deletion versus retained backups — the subtle one

If a user deletes all their data but their rows still sit in yesterday's backup,
the deletion promise is incomplete.

### The policy chosen

**Backups are purged on the retention schedule, and deletion requests are
replayed against any backup that is restored.**

Concretely:

1. `DELETE /api/user/me` erases every row across every table immediately.
2. Existing encrypted backups still contain those rows until they age out — at
   most **28 days** under the 7-daily + 4-weekly policy.
3. A `deletion_requests` ledger records the user ID and the request time.
4. **Any restore replays that ledger before the database is brought back into
   service**, so restoring a backup cannot resurrect deleted data.

### Why this and not the alternative

The alternative — rewriting every retained backup on each deletion request —
sounds cleaner and is worse. It means decrypting and re-encrypting the entire
backup set on demand, which turns a routine user action into a heavyweight
operation, and creates a window where backups are being rewritten and are
therefore not restorable. It also means the backup set is no longer an immutable
record, which undermines its use as evidence after an incident.

The 28-day bound is stated to users in the deletion confirmation rather than
being quietly true.

### Honest limitation

Between the deletion request and the backup ageing out, the data exists in
encrypted form on disk. It is unreadable without `BACKUP_KEY`, and it can never
be served to anyone because the replay happens before a restored database goes
live — but it exists. Claiming instant erasure everywhere would be false.

---

## Threats this covers, and does not

**Covers:** accidental deletion, database corruption, a failed migration,
ransomware on the live file, recovery after an incident.

**Does not cover:** loss of `BACKUP_KEY` — the backups become permanently
undecryptable. Store it separately from the backup files themselves. This is also
why the incident response procedure warns that rotating `BACKUP_KEY` orphans
existing backups.

---

## Schedule

| Task | Frequency |
|---|---|
| `backup create` | daily |
| `backup verify` | weekly |
| Full corruption-and-restore drill | before every release tag |
| Review retention policy | quarterly |
