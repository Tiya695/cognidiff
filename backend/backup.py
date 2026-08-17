"""Encrypted backup, retention and restore.

Availability is part of health-data security, not something separate from it. A
system that protects data perfectly and then loses it has still failed the
person relying on it.

Two details that are easy to get wrong and expensive to get wrong:

  * Backups use ``sqlite3.Connection.backup()``, never a file copy. Copying a
    live SQLite file can capture it mid-write and produce a backup that restores
    to a corrupted database, and you find out at the worst possible moment.

  * An untested backup is not a backup. ``verify_restore()`` exists so the
    restore path is exercised, not assumed.

    python -m backend.backup create
    python -m backend.backup list
    python -m backend.backup restore cognidiff_20260817_1430.db.enc
    python -m backend.backup verify
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

from .config import BACKUP_DIR, BACKUP_KEY, DB_PATH

KEEP_DAILY = 7
KEEP_WEEKLY = 4

try:
    from cryptography.fernet import Fernet, InvalidToken
    HAS_CRYPTO = True
except ImportError:  # pragma: no cover - depends on environment
    Fernet = None
    InvalidToken = Exception
    HAS_CRYPTO = False


class BackupError(RuntimeError):
    pass


def _cipher():
    if not HAS_CRYPTO:
        raise BackupError("cryptography is not installed, cannot encrypt backups.")
    if not BACKUP_KEY:
        raise BackupError(
            "BACKUP_KEY is not set. Generate one with:\n"
            "  python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    try:
        return Fernet(BACKUP_KEY.encode())
    except Exception as exc:
        raise BackupError(f"BACKUP_KEY is not a valid Fernet key: {exc}")


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

def create_backup(source: Path | None = None) -> Path:
    """Take a consistent snapshot, encrypt it, and apply the retention policy."""
    source = Path(source or DB_PATH)
    if not source.exists():
        raise BackupError(f"no database at {source}")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    staging = BACKUP_DIR / f".staging_{stamp}.db"

    # Connection.backup() is transaction-aware: it copies a consistent snapshot
    # even while the application is writing.
    src = sqlite3.connect(str(source))
    dst = sqlite3.connect(str(staging))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    try:
        payload = staging.read_bytes()
        target = BACKUP_DIR / f"cognidiff_{stamp}.db.enc"
        target.write_bytes(_cipher().encrypt(payload))
    finally:
        staging.unlink(missing_ok=True)

    apply_retention()
    return target


# ---------------------------------------------------------------------------
# retention
# ---------------------------------------------------------------------------

def list_backups() -> list[Path]:
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.glob("cognidiff_*.db.enc"), reverse=True)


def _taken_at(path: Path) -> datetime:
    stamp = path.name.replace("cognidiff_", "").replace(".db.enc", "")
    return datetime.strptime(stamp, "%Y%m%d_%H%M")


def apply_retention() -> list[Path]:
    """Keep the last 7 daily and 4 weekly backups; delete the rest.

    Retention is not only a disk-space policy, it is half of the deletion
    promise. See docs/backup_recovery.md.
    """
    backups = list_backups()
    now = datetime.now()

    keep: set[Path] = set()

    # newest backup per day, for the last 7 days
    by_day: dict[str, Path] = {}
    for b in backups:
        taken = _taken_at(b)
        if now - taken <= timedelta(days=KEEP_DAILY):
            by_day.setdefault(taken.strftime("%Y-%m-%d"), b)
    keep.update(by_day.values())

    # newest backup per ISO week, for the last 4 weeks
    by_week: dict[str, Path] = {}
    for b in backups:
        taken = _taken_at(b)
        if now - taken <= timedelta(weeks=KEEP_WEEKLY):
            by_week.setdefault(taken.strftime("%G-W%V"), b)
    keep.update(by_week.values())

    removed = []
    for b in backups:
        if b not in keep:
            b.unlink(missing_ok=True)
            removed.append(b)
    return removed


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------

def restore_backup(
    name: str,
    target: Path | None = None,
    replay_deletions_on_restore: bool = True,
) -> Path:
    """Decrypt and restore. The existing database is moved aside, never
    overwritten in place, a failed restore must not also destroy what was
    there."""
    source = BACKUP_DIR / name if not Path(name).is_absolute() else Path(name)
    if not source.exists():
        raise BackupError(f"no backup named {name}")

    target = Path(target or DB_PATH)

    try:
        plaintext = _cipher().decrypt(source.read_bytes())
    except InvalidToken:
        raise BackupError(
            "Could not decrypt. The BACKUP_KEY does not match the one this "
            "backup was written with."
        )

    if target.exists():
        aside = target.with_suffix(
            f".pre-restore-{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        )
        target.replace(aside)

    target.write_bytes(plaintext)

    # An unreadable restore is a failed restore, so prove it opens.
    conn = sqlite3.connect(str(target))
    try:
        conn.execute("PRAGMA integrity_check").fetchone()
    finally:
        conn.close()

    # Honour deletions that happened after this backup was taken. A backup from
    # before a user asked to be erased still contains their rows; restoring it
    # without this replay would quietly resurrect them.
    if replay_deletions_on_restore:
        from . import database as db
        result = db.replay_deletions(target)
        if result["rows_removed"]:
            print(f"  replayed {result['users_replayed']} deletion request(s), "
                  f"removed {result['rows_removed']} row(s)")

    return target


def verify_restore(name: str | None = None) -> dict:
    """Restore into a scratch file and compare row counts against live.

    This is the test that turns a backup into a backup.
    """
    backups = list_backups()
    if not backups:
        raise BackupError("no backups to verify")
    chosen = BACKUP_DIR / name if name else backups[0]

    scratch = BACKUP_DIR / ".verify.db"
    scratch.unlink(missing_ok=True)
    # Verification compares the backup against live as-taken, so the deletion
    # replay is skipped here, it would make the row counts differ by design.
    restore_backup(chosen.name, target=scratch, replay_deletions_on_restore=False)

    # Literal statements rather than a loop over interpolated table names, so
    # there is no string-built SQL anywhere in the project for a scanner, or a
    # reviewer, to have to reason about.
    COUNT_QUERIES = (
        ("users",              "SELECT COUNT(*) FROM users"),
        ("keystroke_sessions", "SELECT COUNT(*) FROM keystroke_sessions"),
        ("cogniscores",        "SELECT COUNT(*) FROM cogniscores"),
        ("task_results",       "SELECT COUNT(*) FROM task_results"),
        ("daily_context",      "SELECT COUNT(*) FROM daily_context"),
        ("consent_grants",     "SELECT COUNT(*) FROM consent_grants"),
        ("security_audit_log", "SELECT COUNT(*) FROM security_audit_log"),
    )

    def counts(path: Path) -> dict[str, int]:
        conn = sqlite3.connect(str(path))
        try:
            out = {}
            for table, sql in COUNT_QUERIES:
                try:
                    out[table] = conn.execute(sql).fetchone()[0]
                except sqlite3.Error:
                    out[table] = -1
            return out
        finally:
            conn.close()

    live = counts(Path(DB_PATH)) if Path(DB_PATH).exists() else {}
    restored = counts(scratch)
    scratch.unlink(missing_ok=True)

    return {
        "backup": chosen.name,
        "restored_counts": restored,
        "live_counts": live,
        "readable": all(v >= 0 for v in restored.values()),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="CogniDiff backup tool")
    parser.add_argument("action",
                        choices=["create", "list", "restore", "verify", "prune"])
    parser.add_argument("name", nargs="?", help="backup filename, for restore")
    args = parser.parse_args()

    try:
        if args.action == "create":
            path = create_backup()
            size = path.stat().st_size / 1024
            print(f"created {path.name} ({size:.1f} KB, encrypted)")

        elif args.action == "list":
            backups = list_backups()
            if not backups:
                print("no backups yet")
            for b in backups:
                print(f"  {b.name:<38} {b.stat().st_size / 1024:>8.1f} KB  "
                      f"{_taken_at(b):%Y-%m-%d %H:%M}")

        elif args.action == "restore":
            if not args.name:
                print("restore needs a backup name; run `list` first")
                return 2
            print(f"restored to {restore_backup(args.name)}")

        elif args.action == "verify":
            result = verify_restore(args.name)
            print(f"backup   {result['backup']}")
            print(f"readable {result['readable']}")
            for table, n in result["restored_counts"].items():
                live = result["live_counts"].get(table, ",")
                flag = "" if live == n else "   <- differs from live"
                print(f"  {table:<22} restored {n:>6}   live {live}{flag}")

        elif args.action == "prune":
            removed = apply_retention()
            print(f"removed {len(removed)} backup(s) outside the retention window")

    except BackupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
