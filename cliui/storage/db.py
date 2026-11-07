"""SQLite schema and connection helpers."""

from __future__ import annotations

import os
import sqlite3
import typing as t
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    app TEXT NOT NULL,
    title TEXT,
    status TEXT NOT NULL,
    total INTEGER NOT NULL DEFAULT 0,
    succeeded INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    app TEXT NOT NULL,
    command_id TEXT NOT NULL,
    command_path TEXT NOT NULL,
    params_json TEXT NOT NULL,
    argv_json TEXT NOT NULL,
    argv_label TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    exit_code INTEGER,
    stdout TEXT,
    stderr TEXT,
    exception TEXT,
    duration_ms INTEGER,
    batch_id INTEGER,
    batch_index INTEGER,
    trigger TEXT NOT NULL DEFAULT 'manual',
    schedule_id INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_specs (
    name TEXT PRIMARY KEY,
    import_spec TEXT NOT NULL,
    base_cwd TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_name TEXT NOT NULL,
    command_path TEXT NOT NULL,
    argv_json TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    argv_label TEXT NOT NULL DEFAULT '',
    cron TEXT,
    run_at TEXT,
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    catch_up INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER NOT NULL,
    created_by_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    next_run_at TEXT,
    last_run_at TEXT,
    last_status TEXT,
    last_execution_id INTEGER
);

CREATE TABLE IF NOT EXISTS queue_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    app TEXT NOT NULL,
    command_id TEXT NOT NULL,
    command_path TEXT NOT NULL,
    params_json TEXT NOT NULL,
    argv_json TEXT NOT NULL,
    params_label TEXT NOT NULL DEFAULT '',
    argv_label TEXT NOT NULL DEFAULT '',
    seq INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_executions_user ON executions(user_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_executions_created ON executions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_executions_batch ON executions(batch_id, batch_index);
CREATE INDEX IF NOT EXISTS idx_executions_command ON executions(command_path);
CREATE INDEX IF NOT EXISTS idx_schedules_enabled ON schedules(enabled, next_run_at);
CREATE INDEX IF NOT EXISTS idx_queue_user ON queue_items(user_id, seq);
CREATE INDEX IF NOT EXISTS idx_batches_user ON batches(user_id, id DESC);
"""

# Columns added after the first release.  ``CREATE TABLE IF NOT EXISTS`` never
# touches an existing table, so older databases are upgraded in place.
MIGRATIONS: t.List[t.Tuple[str, str, str]] = [
    ("executions", "trigger", "ALTER TABLE executions ADD COLUMN trigger TEXT NOT NULL DEFAULT 'manual'"),
    ("executions", "schedule_id", "ALTER TABLE executions ADD COLUMN schedule_id INTEGER"),
]


def connect(db_path: str | os.PathLike[str]) -> sqlite3.Connection:
    path = str(db_path)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, ddl in MIGRATIONS:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        if not rows:
            continue
        if any(row["name"] == column for row in rows):
            continue
        conn.execute(ddl)


def init_db(db_path: str | os.PathLike[str]) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.executescript(SCHEMA)
        _migrate(conn)
        # Depends on a migrated column, so it cannot live in SCHEMA.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_executions_schedule "
            "ON executions(schedule_id, id DESC)"
        )
        conn.commit()
    finally:
        conn.close()
