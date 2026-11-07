"""Persistence layer: users, executions, queue and batches."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import typing as t
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from cliui.storage.db import connect, init_db

PASSWORD_ITERATIONS = 200_000


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hash_password(password: str, iterations: int = PASSWORD_ITERATIONS) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations_text, salt, digest_hex = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("ascii"), iterations
        ).hex()
        return hmac.compare_digest(digest, digest_hex)
    except Exception:
        return False


def summarize_params(field_values: t.Dict[str, t.Any]) -> str:
    parts: t.List[str] = []
    for key, value in field_values.items():
        if value in (None, "", [], {}, False):
            continue
        short_key = key.split("__", 1)[-1] if "__" in key else key
        text = str(value)
        if len(text) > 48:
            text = text[:45] + "..."
        parts.append(f"{short_key}={text}")
        if len(parts) >= 6:
            break
    summary = ", ".join(parts)
    return summary[:360]


class Store:
    def __init__(self, db_path: str | os.PathLike[str]):
        self.db_path = Path(db_path)
        init_db(self.db_path)

    @contextmanager
    def _db(self) -> t.Iterator[sqlite3.Connection]:
        conn = connect(self.db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ----------------------------------------------------------------- users
    def count_users(self) -> int:
        with self._db() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
            return int(row["n"])

    def create_user(self, username: str, password: str, is_admin: bool = False) -> bool:
        username = username.strip()
        if not username or len(username) > 64:
            raise ValueError("用户名长度需要在 1-64 个字符之间")
        if len(password) < 6:
            raise ValueError("密码至少需要 6 个字符")
        with self._db() as conn:
            exists = conn.execute(
                "SELECT 1 FROM users WHERE username = ? COLLATE NOCASE", (username,)
            ).fetchone()
            if exists:
                return False
            conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
                (username, hash_password(password), 1 if is_admin else 0, now_str()),
            )
            return True

    def get_user(self, user_id: int) -> t.Optional[t.Dict[str, t.Any]]:
        with self._db() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    def get_user_by_name(self, username: str) -> t.Optional[t.Dict[str, t.Any]]:
        with self._db() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
            ).fetchone()
            return dict(row) if row else None

    def list_users(self) -> t.List[t.Dict[str, t.Any]]:
        with self._db() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
            return [dict(row) for row in rows]

    def authenticate(self, username: str, password: str) -> t.Optional[t.Dict[str, t.Any]]:
        user = self.get_user_by_name(username)
        if not user or not verify_password(password, user["password_hash"]):
            return None
        with self._db() as conn:
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_str(), user["id"]))
        user["last_login_at"] = now_str()
        return user

    def ensure_admin(self, password: str) -> t.Tuple[bool, str]:
        if self.count_users() > 0:
            return False, ""
        self.create_user("admin", password, is_admin=True)
        return True, password

    # ------------------------------------------------------------ executions
    def record_execution(
        self,
        *,
        user_id: int,
        username: str,
        app: str,
        command_id: str,
        command_path: str,
        params: t.Dict[str, t.Any],
        argv: t.List[str],
        argv_label: str,
        status: str,
        exit_code: t.Optional[int],
        stdout: str,
        stderr: str,
        exception: str,
        duration_ms: int,
        batch_id: t.Optional[int] = None,
        batch_index: t.Optional[int] = None,
        trigger: str = "manual",
        schedule_id: t.Optional[int] = None,
    ) -> int:
        with self._db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO executions
                (user_id, username, app, command_id, command_path, params_json, argv_json,
                 argv_label, status, exit_code, stdout, stderr, exception, duration_ms,
                 batch_id, batch_index, trigger, schedule_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    username,
                    app,
                    command_id,
                    command_path,
                    json.dumps(params, ensure_ascii=False),
                    json.dumps(argv, ensure_ascii=False),
                    argv_label,
                    status,
                    exit_code,
                    stdout,
                    stderr,
                    exception,
                    duration_ms,
                    batch_id,
                    batch_index,
                    trigger,
                    schedule_id,
                    now_str(),
                ),
            )
            return int(cursor.lastrowid)

    def get_execution(self, execution_id: int) -> t.Optional[t.Dict[str, t.Any]]:
        with self._db() as conn:
            row = conn.execute("SELECT * FROM executions WHERE id = ?", (execution_id,)).fetchone()
            return dict(row) if row else None

    def list_executions(
        self,
        *,
        user_id: t.Optional[int],
        page: int = 1,
        per_page: int = 20,
        app: t.Optional[str] = None,
        command: t.Optional[str] = None,
        status: t.Optional[str] = None,
        username: t.Optional[str] = None,
        trigger: t.Optional[str] = None,
    ) -> t.Tuple[t.List[t.Dict[str, t.Any]], int]:
        page = max(1, int(page))
        per_page = max(1, min(200, int(per_page)))
        where: t.List[str] = []
        params: t.List[t.Any] = []
        if user_id is not None:
            where.append("user_id = ?")
            params.append(user_id)
        if app:
            where.append("app = ?")
            params.append(app)
        if command:
            where.append("command_path LIKE ?")
            params.append(f"%{command}%")
        if status:
            where.append("status = ?")
            params.append(status)
        if username:
            where.append("username = ? COLLATE NOCASE")
            params.append(username)
        if trigger:
            where.append("trigger = ?")
            params.append(trigger)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        with self._db() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS n FROM executions{clause}", params).fetchone()["n"]
            rows = conn.execute(
                f"SELECT * FROM executions{clause} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [per_page, (page - 1) * per_page],
            ).fetchall()
            return [dict(row) for row in rows], int(total)

    # ---------------------------------------------------------------- queue
    def queue_count(self, user_id: int) -> int:
        with self._db() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM queue_items WHERE user_id = ?", (user_id,)
            ).fetchone()
            return int(row["n"])

    def add_queue_item(
        self,
        *,
        user_id: int,
        username: str,
        app: str,
        command_id: str,
        command_path: str,
        params: t.Dict[str, t.Any],
        argv: t.List[str],
        params_label: str,
        argv_label: str,
    ) -> int:
        with self._db() as conn:
            seq_row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS seq FROM queue_items WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            cursor = conn.execute(
                """
                INSERT INTO queue_items
                (user_id, username, app, command_id, command_path, params_json, argv_json,
                 params_label, argv_label, seq, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    username,
                    app,
                    command_id,
                    command_path,
                    json.dumps(params, ensure_ascii=False),
                    json.dumps(argv, ensure_ascii=False),
                    params_label,
                    argv_label,
                    int(seq_row["seq"]),
                    now_str(),
                ),
            )
            return int(cursor.lastrowid)

    def list_queue(
        self, *, user_id: int, page: int = 1, per_page: int = 20
    ) -> t.Tuple[t.List[t.Dict[str, t.Any]], int]:
        page = max(1, int(page))
        per_page = max(1, min(200, int(per_page)))
        with self._db() as conn:
            total = conn.execute(
                "SELECT COUNT(*) AS n FROM queue_items WHERE user_id = ?", (user_id,)
            ).fetchone()["n"]
            rows = conn.execute(
                "SELECT * FROM queue_items WHERE user_id = ? ORDER BY seq, id LIMIT ? OFFSET ?",
                (user_id, per_page, (page - 1) * per_page),
            ).fetchall()
            return [dict(row) for row in rows], int(total)

    def queue_items(self, user_id: int) -> t.List[t.Dict[str, t.Any]]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT * FROM queue_items WHERE user_id = ? ORDER BY seq, id", (user_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    def get_queue_item(self, item_id: int, user_id: int) -> t.Optional[t.Dict[str, t.Any]]:
        with self._db() as conn:
            row = conn.execute(
                "SELECT * FROM queue_items WHERE id = ? AND user_id = ?", (item_id, user_id)
            ).fetchone()
            return dict(row) if row else None

    def delete_queue_item(self, item_id: int, user_id: int) -> bool:
        with self._db() as conn:
            cursor = conn.execute(
                "DELETE FROM queue_items WHERE id = ? AND user_id = ?", (item_id, user_id)
            )
            return cursor.rowcount > 0

    def clear_queue(self, user_id: int) -> int:
        with self._db() as conn:
            cursor = conn.execute("DELETE FROM queue_items WHERE user_id = ?", (user_id,))
            return cursor.rowcount

    def move_queue_item(self, item_id: int, user_id: int, direction: str) -> bool:
        with self._db() as conn:
            item = conn.execute(
                "SELECT * FROM queue_items WHERE id = ? AND user_id = ?", (item_id, user_id)
            ).fetchone()
            if not item:
                return False
            if direction == "up":
                neighbor = conn.execute(
                    "SELECT * FROM queue_items WHERE user_id = ? AND seq < ? ORDER BY seq DESC LIMIT 1",
                    (user_id, item["seq"]),
                ).fetchone()
            else:
                neighbor = conn.execute(
                    "SELECT * FROM queue_items WHERE user_id = ? AND seq > ? ORDER BY seq ASC LIMIT 1",
                    (user_id, item["seq"]),
                ).fetchone()
            if not neighbor:
                return False
            conn.execute(
                "UPDATE queue_items SET seq = ? WHERE id = ?", (neighbor["seq"], item["id"])
            )
            conn.execute(
                "UPDATE queue_items SET seq = ? WHERE id = ?", (item["seq"], neighbor["id"])
            )
            return True

    # --------------------------------------------------------------- batches
    def create_batch(
        self, *, user_id: int, username: str, app: str, status: str = "running", title: str = ""
    ) -> int:
        with self._db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO batches (user_id, username, app, title, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, username, app, title, status, now_str()),
            )
            return int(cursor.lastrowid)

    def update_batch(
        self, batch_id: int, *, status: str, total: int, succeeded: int, failed: int
    ) -> None:
        with self._db() as conn:
            conn.execute(
                """
                UPDATE batches SET status = ?, total = ?, succeeded = ?, failed = ?, finished_at = ?
                WHERE id = ?
                """,
                (status, total, succeeded, failed, now_str(), batch_id),
            )

    def get_batch(self, batch_id: int) -> t.Optional[t.Dict[str, t.Any]]:
        with self._db() as conn:
            row = conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
            return dict(row) if row else None

    def list_batches(
        self, *, user_id: t.Optional[int], page: int = 1, per_page: int = 20
    ) -> t.Tuple[t.List[t.Dict[str, t.Any]], int]:
        page = max(1, int(page))
        per_page = max(1, min(200, int(per_page)))
        clause = " WHERE user_id = ?" if user_id is not None else ""
        params: t.List[t.Any] = [user_id] if user_id is not None else []
        with self._db() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS n FROM batches{clause}", params).fetchone()["n"]
            rows = conn.execute(
                f"SELECT * FROM batches{clause} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [per_page, (page - 1) * per_page],
            ).fetchall()
            return [dict(row) for row in rows], int(total)

    def batch_executions(self, batch_id: int) -> t.List[t.Dict[str, t.Any]]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT * FROM executions WHERE batch_id = ? ORDER BY batch_index, id", (batch_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    # ------------------------------------------------------------ app specs
    def save_app_specs(self, specs: t.Sequence[t.Tuple[str, str, str]]) -> None:
        """Remember which applications the console serves.

        The standalone scheduler process has no command line of its own, so
        ``serve`` publishes the registered specs here and the scheduler loads
        them back by name.
        """
        timestamp = now_str()
        names = [name for name, _spec, _cwd in specs]
        with self._db() as conn:
            for name, spec, base_cwd in specs:
                conn.execute(
                    """
                    INSERT INTO app_specs (name, import_spec, base_cwd, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        import_spec = excluded.import_spec,
                        base_cwd = excluded.base_cwd,
                        updated_at = excluded.updated_at
                    """,
                    (name, spec, base_cwd or "", timestamp),
                )
            if names:
                placeholders = ", ".join("?" for _ in names)
                conn.execute(
                    f"DELETE FROM app_specs WHERE name NOT IN ({placeholders})", names
                )
            else:
                conn.execute("DELETE FROM app_specs")

    def load_app_specs(self) -> t.List[t.Dict[str, t.Any]]:
        with self._db() as conn:
            rows = conn.execute("SELECT * FROM app_specs ORDER BY name").fetchall()
            return [dict(row) for row in rows]

    # ----------------------------------------------------------- schedules
    def create_schedule(
        self,
        *,
        app_name: str,
        command_path: str,
        argv: t.List[str],
        params: t.Dict[str, t.Any],
        argv_label: str,
        cron: t.Optional[str],
        run_at: t.Optional[str],
        timezone: str,
        catch_up: bool,
        enabled: bool,
        created_by: int,
        created_by_name: str,
        next_run_at: t.Optional[str],
    ) -> int:
        with self._db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO schedules
                (app_name, command_path, argv_json, params_json, argv_label, cron, run_at,
                 timezone, catch_up, enabled, created_by, created_by_name, created_at,
                 updated_at, next_run_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    app_name,
                    command_path,
                    json.dumps(argv, ensure_ascii=False),
                    json.dumps(params, ensure_ascii=False),
                    argv_label,
                    cron,
                    run_at,
                    timezone,
                    1 if catch_up else 0,
                    1 if enabled else 0,
                    created_by,
                    created_by_name,
                    now_str(),
                    now_str(),
                    next_run_at,
                ),
            )
            return int(cursor.lastrowid)

    def get_schedule(self, schedule_id: int) -> t.Optional[t.Dict[str, t.Any]]:
        with self._db() as conn:
            row = conn.execute(
                "SELECT * FROM schedules WHERE id = ?", (schedule_id,)
            ).fetchone()
            return dict(row) if row else None

    def list_schedules(
        self,
        *,
        user_id: t.Optional[int],
        page: int = 1,
        per_page: int = 20,
        app: t.Optional[str] = None,
    ) -> t.Tuple[t.List[t.Dict[str, t.Any]], int]:
        page = max(1, int(page))
        per_page = max(1, min(200, int(per_page)))
        where: t.List[str] = []
        params: t.List[t.Any] = []
        if user_id is not None:
            where.append("created_by = ?")
            params.append(user_id)
        if app:
            where.append("app_name = ?")
            params.append(app)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        with self._db() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS n FROM schedules{clause}", params
            ).fetchone()["n"]
            rows = conn.execute(
                f"SELECT * FROM schedules{clause} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [per_page, (page - 1) * per_page],
            ).fetchall()
            return [dict(row) for row in rows], int(total)

    def enabled_schedules(self) -> t.List[t.Dict[str, t.Any]]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT * FROM schedules WHERE enabled = 1 ORDER BY next_run_at, id"
            ).fetchall()
            return [dict(row) for row in rows]

    def set_schedule_enabled(
        self, schedule_id: int, enabled: bool, next_run_at: t.Optional[str]
    ) -> bool:
        with self._db() as conn:
            cursor = conn.execute(
                """
                UPDATE schedules SET enabled = ?, next_run_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (1 if enabled else 0, next_run_at, now_str(), schedule_id),
            )
            return cursor.rowcount > 0

    def update_schedule_next_run(
        self, schedule_id: int, next_run_at: t.Optional[str]
    ) -> None:
        with self._db() as conn:
            conn.execute(
                "UPDATE schedules SET next_run_at = ?, updated_at = ? WHERE id = ?",
                (next_run_at, now_str(), schedule_id),
            )

    def mark_schedule_missed(self, schedule_id: int, next_run_at: t.Optional[str]) -> None:
        with self._db() as conn:
            conn.execute(
                """
                UPDATE schedules SET last_status = 'missed', next_run_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (next_run_at, now_str(), schedule_id),
            )

    def delete_schedule(self, schedule_id: int) -> bool:
        with self._db() as conn:
            cursor = conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
            return cursor.rowcount > 0

    def claim_schedule_run(
        self,
        schedule_id: int,
        *,
        expected_next_run_at: t.Optional[str],
        next_run_at: t.Optional[str],
        now: str,
    ) -> bool:
        """Atomically take ownership of one scheduled fire.

        Only the writer whose ``expected_next_run_at`` still matches wins, so
        two scheduler processes can never run the same fire twice.
        """
        with self._db() as conn:
            cursor = conn.execute(
                """
                UPDATE schedules SET last_run_at = ?, next_run_at = ?, updated_at = ?
                WHERE id = ? AND enabled = 1 AND next_run_at IS ?
                """,
                (now, next_run_at, now_str(), schedule_id, expected_next_run_at),
            )
            return cursor.rowcount > 0

    def mark_schedule_result(
        self, schedule_id: int, *, status: str, execution_id: t.Optional[int]
    ) -> None:
        with self._db() as conn:
            conn.execute(
                """
                UPDATE schedules SET last_status = ?, last_execution_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, execution_id, now_str(), schedule_id),
            )

    def finish_schedule_run(
        self,
        schedule_id: int,
        *,
        status: str,
        execution_id: t.Optional[int],
        next_run_at: t.Optional[str],
        enabled: t.Optional[bool] = None,
    ) -> None:
        with self._db() as conn:
            if enabled is None:
                conn.execute(
                    """
                    UPDATE schedules SET last_status = ?, last_execution_id = ?,
                        next_run_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (status, execution_id, next_run_at, now_str(), schedule_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE schedules SET last_status = ?, last_execution_id = ?,
                        next_run_at = ?, enabled = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        status,
                        execution_id,
                        next_run_at,
                        1 if enabled else 0,
                        now_str(),
                        schedule_id,
                    ),
                )
