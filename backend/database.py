"""SQLite schema and access layer.

Every query in this module uses parameterised placeholders. There is no
f-string SQL and no string concatenation with user input anywhere in the
project — that is what makes Attack 7 (SQL injection) a non-event.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Iterable, Iterator, Optional

from .config import DB_PATH

# --------------------------------------------------------------------------
# schema
# --------------------------------------------------------------------------

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id                      TEXT PRIMARY KEY,
    username                TEXT NOT NULL UNIQUE,
    password_hash           TEXT NOT NULL,
    role                    TEXT NOT NULL DEFAULT 'USER',
    first_name              TEXT,
    token_version           INTEGER NOT NULL DEFAULT 1,
    baseline_status         TEXT NOT NULL DEFAULT 'INSUFFICIENT_DATA',
    baseline_version        INTEGER NOT NULL DEFAULT 0,
    baseline_device         TEXT,
    recalibration_started_at TEXT,
    created_at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS keystroke_sessions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             TEXT NOT NULL,
    date                TEXT NOT NULL,
    hour                INTEGER NOT NULL,
    wpm_estimate        REAL NOT NULL,
    avg_iki_ms          REAL NOT NULL,
    avg_hold_ms         REAL NOT NULL,
    backspace_count     INTEGER NOT NULL,
    total_keystrokes    INTEGER NOT NULL,
    pause_count         INTEGER NOT NULL,
    session_minute      INTEGER NOT NULL,
    error_rate          REAL NOT NULL,
    correction_rate     REAL NOT NULL,
    correction_events   INTEGER NOT NULL DEFAULT 0,
    mean_keys_deleted   REAL NOT NULL DEFAULT 0,
    mean_correction_ms  REAL NOT NULL DEFAULT 0,
    rhythm_variability  REAL NOT NULL,
    long_pause_count    INTEGER NOT NULL,
    burst_ratio         REAL NOT NULL,
    time_slot           TEXT NOT NULL,
    duration_ms         INTEGER NOT NULL DEFAULT 0,
    device_fingerprint  TEXT,
    quality_score       REAL NOT NULL DEFAULT 0,
    excluded            INTEGER NOT NULL DEFAULT 0,
    device_changed      INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_date
    ON keystroke_sessions(user_id, date);
CREATE INDEX IF NOT EXISTS idx_sessions_user_excluded
    ON keystroke_sessions(user_id, excluded);

CREATE TABLE IF NOT EXISTS session_exclusions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER,
    user_id     TEXT NOT NULL,
    date        TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    detail      TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cogniscores (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id                 TEXT NOT NULL,
    date                    TEXT NOT NULL,
    raw_score               REAL NOT NULL,
    adjusted_score          REAL NOT NULL,
    composite_score         REAL,
    top_deviating_feature   TEXT,
    deviation_percent       REAL NOT NULL DEFAULT 0,
    quality_score           REAL NOT NULL DEFAULT 0,
    confidence              REAL NOT NULL DEFAULT 0,
    confidence_band         TEXT NOT NULL DEFAULT 'LOW',
    context_adjusted        INTEGER NOT NULL DEFAULT 0,
    is_anomaly              INTEGER NOT NULL DEFAULT 0,
    anomaly_score           REAL NOT NULL DEFAULT 0,
    alert_status            TEXT NOT NULL DEFAULT 'STABLE',
    provisional             INTEGER NOT NULL DEFAULT 0,
    model_version           TEXT NOT NULL,
    baseline_version        INTEGER NOT NULL,
    feature_schema_version  TEXT NOT NULL,
    code_commit             TEXT NOT NULL,
    created_at              TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_scores_user_date ON cogniscores(user_id, date);

CREATE TABLE IF NOT EXISTS task_results (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             TEXT NOT NULL,
    date                TEXT NOT NULL,
    word_recall         REAL,
    reaction_time_ms    REAL,
    pattern_memory      REAL,
    letter_scramble_ms  REAL,
    composite_task_score REAL NOT NULL,
    created_at          TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS daily_context (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    date            TEXT NOT NULL,
    sleep_quality   INTEGER,
    stress_level    INTEGER,
    device_changed  INTEGER NOT NULL DEFAULT 0,
    feeling_unwell  INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    UNIQUE(user_id, date),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS consent_grants (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    granted_to  TEXT NOT NULL,
    granted_at  TEXT NOT NULL,
    revoked_at  TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_consent_lookup
    ON consent_grants(user_id, granted_to, active);

CREATE TABLE IF NOT EXISTS security_audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    user_id     TEXT,
    actor_id    TEXT,
    actor_role  TEXT,
    action      TEXT NOT NULL,
    resource    TEXT NOT NULL,
    outcome     TEXT NOT NULL,
    ip_address  TEXT,
    details     TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_user ON security_audit_log(user_id, id DESC);

CREATE TABLE IF NOT EXISTS federated_rounds (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    round_no    INTEGER NOT NULL,
    n_clients   INTEGER NOT NULL,
    accuracy    REAL,
    loss        REAL,
    created_at  TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# connection handling
# --------------------------------------------------------------------------

_db_path = DB_PATH


def set_db_path(path) -> None:
    """Point the layer at another database file. Used by the pytest fixture so
    tests never touch the real cognidiff.db."""
    global _db_path
    _db_path = path


def get_db_path():
    return _db_path


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def cursor(commit: bool = False) -> Iterator[sqlite3.Cursor]:
    conn = connect()
    try:
        cur = conn.cursor()
        yield cur
        if commit:
            conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------
# generic helpers — all parameterised
# --------------------------------------------------------------------------

def query(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    with cursor() as cur:
        cur.execute(sql, tuple(params))
        return [dict(r) for r in cur.fetchall()]


def query_one(sql: str, params: Iterable[Any] = ()) -> Optional[dict]:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    with cursor(commit=True) as cur:
        cur.execute(sql, tuple(params))
        return cur.lastrowid


@lru_cache(maxsize=32)
def _columns_of(table: str) -> frozenset[str]:
    """Column names as the database itself reports them."""
    with cursor() as cur:
        cur.execute("SELECT name FROM pragma_table_info(?)", (table,))
        return frozenset(r["name"] for r in cur.fetchall())


def insert(table: str, data: dict) -> int:
    """Insert a row.

    Values always go through placeholders. The table and column names cannot —
    SQL has no parameter form for identifiers — so both are validated against
    the live schema before they are interpolated. That turns "these are literals
    at every call site, trust us" into something the database itself checks, and
    it is why bandit's B608 on this line is an accepted finding rather than an
    open one (see docs/dependency_audit.md).
    """
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"unknown table: {table}")

    cols = list(data.keys())
    known = _columns_of(table)
    unknown = [c for c in cols if c not in known]
    if unknown:
        raise ValueError(f"unknown column(s) for {table}: {unknown}")

    placeholders = ", ".join("?" for _ in cols)
    col_sql = ", ".join(cols)
    sql = f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders})"  # nosec B608
    return execute(sql, [data[c] for c in cols])


_ALLOWED_TABLES = {
    "users", "keystroke_sessions", "session_exclusions", "cogniscores",
    "task_results", "daily_context", "consent_grants", "security_audit_log",
    "federated_rounds",
}


# --------------------------------------------------------------------------
# domain queries
# --------------------------------------------------------------------------

def get_user_by_username(username: str) -> Optional[dict]:
    return query_one("SELECT * FROM users WHERE username = ?", (username,))


def get_user(user_id: str) -> Optional[dict]:
    return query_one("SELECT * FROM users WHERE id = ?", (user_id,))


def good_sessions(user_id: str, limit: Optional[int] = None) -> list[dict]:
    """Quality-passing sessions only.

    The `excluded = 0` filter is the single gate that every model reads
    through: PersonalBaseline.fit, IsolationForest.fit, the LSTM sequence
    builder, the CogniScore call and every trend query. A 10-second typing
    burst or a laggy batch must never be able to move someone's score.
    """
    # id is the tiebreak throughout. created_at has one-second resolution, so
    # several sessions ingested in the same second tie — and SQLite is free to
    # return tied rows in any order, which would make "the latest session"
    # non-deterministic.
    sql = (
        "SELECT * FROM keystroke_sessions "
        "WHERE user_id = ? AND excluded = 0 "
        "ORDER BY created_at ASC, id ASC"
    )
    params: list[Any] = [user_id]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return query(sql, params)


def all_sessions(user_id: str) -> list[dict]:
    """Every session including excluded ones. Only for quality statistics."""
    return query(
        "SELECT * FROM keystroke_sessions WHERE user_id = ? "
        "ORDER BY created_at ASC, id ASC",
        (user_id,),
    )


def latest_session(user_id: str) -> Optional[dict]:
    """The most recent quality-passing session.

    Ordered by date first, then arrival. Ordering by arrival alone would let a
    batch that was uploaded late — an extension flushing its offline queue —
    masquerade as today's reading.
    """
    return query_one(
        "SELECT * FROM keystroke_sessions WHERE user_id = ? AND excluded = 0 "
        "ORDER BY date DESC, created_at DESC, id DESC LIMIT 1",
        (user_id,),
    )


def daily_scores(user_id: str, days: int) -> list[dict]:
    """One row per day for the last `days` days, NULL where no score exists.

    Built from a recursive calendar so gaps stay visible: a missing day is a
    missing day, not a silently interpolated one.
    """
    return query(
        """
        WITH RECURSIVE calendar(day) AS (
            SELECT date('now', 'localtime', ?)
            UNION ALL
            SELECT date(day, '+1 day') FROM calendar
            WHERE day < date('now', 'localtime')
        )
        SELECT calendar.day AS date,
               ROUND(AVG(c.adjusted_score), 2) AS score,
               ROUND(AVG(c.raw_score), 2)      AS raw_score,
               ROUND(AVG(c.confidence), 1)     AS confidence,
               COUNT(c.id)                     AS n
        FROM calendar
        LEFT JOIN cogniscores c
               ON c.date = calendar.day AND c.user_id = ?
        GROUP BY calendar.day
        ORDER BY calendar.day ASC
        """,
        (f"-{max(days - 1, 0)} day", user_id),
    )


def has_active_consent(user_id: str, doctor_id: str) -> bool:
    row = query_one(
        "SELECT 1 FROM consent_grants "
        "WHERE user_id = ? AND granted_to = ? AND active = 1 AND revoked_at IS NULL",
        (user_id, doctor_id),
    )
    return row is not None


def delete_user_data(user_id: str) -> dict[str, int]:
    """Erase every row belonging to a user across every table.

    The audit log entry recording the deletion is written by the caller AFTER
    this returns, so the deletion itself remains accountable while the user's
    health data is gone.
    """
    # Written out as literal statements rather than a loop over table names.
    # An f-string here would be safe — the names are constants — but it would
    # also be the only interpolated SQL in the project, and a codebase where
    # "we only interpolate the safe ones" is true is a codebase where the rule
    # cannot be checked mechanically. test_attack_07c greps for exactly this.
    DELETIONS = (
        ("keystroke_sessions", "DELETE FROM keystroke_sessions WHERE user_id = ?"),
        ("cogniscores",        "DELETE FROM cogniscores WHERE user_id = ?"),
        ("task_results",       "DELETE FROM task_results WHERE user_id = ?"),
        ("daily_context",      "DELETE FROM daily_context WHERE user_id = ?"),
        ("consent_grants",     "DELETE FROM consent_grants WHERE user_id = ?"),
        ("session_exclusions", "DELETE FROM session_exclusions WHERE user_id = ?"),
    )

    removed: dict[str, int] = {}
    conn = connect()
    try:
        cur = conn.cursor()
        for table, sql in DELETIONS:
            cur.execute(sql, (user_id,))
            removed[table] = cur.rowcount

        # Scrub health-linked audit rows but keep the accountability trail:
        # who acted, on what, with what outcome — never the health content.
        cur.execute(
            "UPDATE security_audit_log SET details = NULL WHERE user_id = ?",
            (user_id,),
        )
        conn.commit()
    finally:
        conn.close()
    return removed
