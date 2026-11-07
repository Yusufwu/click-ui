"""SQLite schema and connection helpers."""

from __future__ import annotations

import os
import sqlite3
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
    created_at TEXT NOT NULL
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
CREATE INDEX IF NOT EXISTS idx_queue_user ON queue_items(user_id, seq);
CREATE INDEX IF NOT EXISTS idx_batches_user ON batches(user_id, id DESC);
"""


def connect(db_path: str | os.PathLike[str]) -> sqlite3.Connection:
    path = str(db_path)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str | os.PathLike[str]) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
