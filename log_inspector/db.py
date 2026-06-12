"""SQLite 数据库初始化与操作"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator


SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    log_path TEXT NOT NULL,
    parser_type TEXT NOT NULL,
    start_time TEXT,
    end_time TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    status TEXT DEFAULT 'running',
    total_lines INTEGER DEFAULT 0,
    matched_lines INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER REFERENCES scans(id),
    line_number INTEGER,
    timestamp TEXT,
    level TEXT,
    rule_name TEXT,
    category TEXT,
    message TEXT,
    raw_line TEXT,
    metadata TEXT
);

CREATE TABLE IF NOT EXISTS slow_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER REFERENCES scans(id),
    path TEXT,
    method TEXT,
    response_time_ms REAL,
    status_code INTEGER,
    timestamp TEXT
);

CREATE TABLE IF NOT EXISTS exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER REFERENCES scans(id),
    format TEXT,
    file_path TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    status TEXT DEFAULT 'pending',
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS schedule_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_name TEXT NOT NULL,
    started_at TEXT DEFAULT (datetime('now')),
    finished_at TEXT,
    status TEXT DEFAULT 'running',
    lock_key TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS db_migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    applied_at TEXT DEFAULT (datetime('now'))
);
"""


class Database:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with self.connect() as conn:
            conn.executescript(SCHEMA)
        self._run_migrations()

    def _run_migrations(self):
        from log_inspector.db_migrations import MIGRATIONS

        with self.connect() as conn:
            applied = {
                row[0]
                for row in conn.execute("SELECT name FROM db_migrations").fetchall()
            }
            for name, sql in MIGRATIONS:
                if name in applied:
                    continue
                try:
                    conn.executescript(sql)
                    conn.execute(
                        "INSERT INTO db_migrations (name) VALUES (?)", (name,)
                    )
                except sqlite3.OperationalError:
                    pass

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def update_scan(self, scan_id: int, status: str, total_lines: int = 0, matched_lines: int = 0):
        with self.connect() as conn:
            conn.execute(
                "UPDATE scans SET status=?, total_lines=?, matched_lines=? WHERE id=?",
                (status, total_lines, matched_lines, scan_id),
            )

    def insert_findings_batch(self, findings: list[dict[str, Any]]):
        if not findings:
            return
        with self.connect() as conn:
            conn.executemany(
                """INSERT INTO findings (scan_id, line_number, timestamp, level, rule_name,
                   category, message, raw_line, metadata)
                   VALUES (:scan_id, :line_number, :timestamp, :level, :rule_name,
                   :category, :message, :raw_line, :metadata)""",
                findings,
            )

    def insert_slow_requests_batch(self, records: list[dict[str, Any]]):
        if not records:
            return
        with self.connect() as conn:
            conn.executemany(
                """INSERT INTO slow_requests (scan_id, path, method, response_time_ms, status_code, timestamp)
                   VALUES (:scan_id, :path, :method, :response_time_ms, :status_code, :timestamp)""",
                records,
            )

    def get_scan(self, scan_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
            return dict(row) if row else None

    def get_error_summary(self, scan_id: int | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            query = """
                SELECT level, rule_name, category, COUNT(*) as count
                FROM findings
            """
            params: tuple = ()
            if scan_id:
                query += " WHERE scan_id=?"
                params = (scan_id,)
            query += " GROUP BY level, rule_name, category ORDER BY count DESC"
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def create_export(self, scan_id: int, fmt: str, file_path: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO exports (scan_id, format, file_path) VALUES (?, ?, ?)",
                (scan_id, fmt, file_path),
            )
            return cursor.lastrowid

    def update_export(self, export_id: int, status: str, error_message: str | None = None):
        with self.connect() as conn:
            conn.execute(
                "UPDATE exports SET status=?, error_message=? WHERE id=?",
                (status, error_message, export_id),
            )

    def get_export(self, export_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM exports WHERE id=?", (export_id,)).fetchone()
            return dict(row) if row else None

    def get_failed_exports(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM exports WHERE status='failed'").fetchall()
            return [dict(r) for r in rows]

    def acquire_schedule_lock(self, task_name: str, time_window: str) -> bool:
        lock_key = f"{task_name}:{time_window}"
        try:
            with self.connect() as conn:
                conn.execute(
                    "INSERT INTO schedule_runs (task_name, lock_key) VALUES (?, ?)",
                    (task_name, lock_key),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def release_schedule_lock(self, task_name: str, time_window: str, status: str):
        lock_key = f"{task_name}:{time_window}"
        with self.connect() as conn:
            conn.execute(
                "UPDATE schedule_runs SET status=?, finished_at=datetime('now') WHERE lock_key=?",
                (status, lock_key),
            )

    def list_scans(self, limit: int = 20, project_id: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if project_id:
                rows = conn.execute(
                    "SELECT * FROM scans WHERE project_id=? ORDER BY id DESC LIMIT ?",
                    (project_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM scans ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    # ─── Notification operations ────────────────────────────────────────────

    def insert_notification(self, scan_id: int | None, rule_name: str,
                           channel: str, status: str = "sent",
                           error_message: str | None = None) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """INSERT INTO notifications (scan_id, rule_name, channel, status, error_message)
                   VALUES (?, ?, ?, ?, ?)""",
                (scan_id, rule_name, channel, status, error_message),
            )
            return cursor.lastrowid

    def get_notifications(self, scan_id: int | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if scan_id:
                rows = conn.execute(
                    "SELECT * FROM notifications WHERE scan_id=? ORDER BY id DESC", (scan_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM notifications ORDER BY id DESC LIMIT 100"
                ).fetchall()
            return [dict(r) for r in rows]

    # ─── Watch session operations ───────────────────────────────────────────

    def create_watch_session(self, log_path: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO watch_sessions (log_path) VALUES (?)", (log_path,)
            )
            return cursor.lastrowid

    def update_watch_session(self, session_id: int, status: str,
                            total_lines: int = 0, matched_lines: int = 0):
        with self.connect() as conn:
            conn.execute(
                """UPDATE watch_sessions SET status=?, stopped_at=datetime('now'),
                   total_lines=?, matched_lines=? WHERE id=?""",
                (status, total_lines, matched_lines, session_id),
            )

    # ─── Project-scoped queries ─────────────────────────────────────────────

    def ensure_project_exists(self, project_id: str, name: str = ""):
        """确保项目在 projects 表中已注册（FK 约束前置条件）"""
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO projects (project_id, name) VALUES (?, ?)",
                (project_id, name or project_id),
            )

    def create_scan(self, log_path: str, parser_type: str,
                    start_time: str | None = None, end_time: str | None = None,
                    source_type: str = "local", source_name: str = "",
                    project_id: str = "default") -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """INSERT INTO scans (log_path, parser_type, start_time, end_time,
                   source_type, source_name, project_id) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (log_path, parser_type, start_time, end_time,
                 source_type, source_name, project_id),
            )
            return cursor.lastrowid

    def get_findings(self, scan_id: int, project_id: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if project_id:
                rows = conn.execute(
                    "SELECT * FROM findings WHERE scan_id=? AND project_id=?",
                    (scan_id, project_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM findings WHERE scan_id=?", (scan_id,)
                ).fetchall()
            return [dict(r) for r in rows]

    def get_slow_requests(self, scan_id: int | None = None,
                         project_id: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if scan_id and project_id:
                rows = conn.execute(
                    "SELECT * FROM slow_requests WHERE scan_id=? AND project_id=?",
                    (scan_id, project_id),
                ).fetchall()
            elif scan_id:
                rows = conn.execute(
                    "SELECT * FROM slow_requests WHERE scan_id=?", (scan_id,)
                ).fetchall()
            elif project_id:
                rows = conn.execute(
                    "SELECT * FROM slow_requests WHERE project_id=? ORDER BY response_time_ms DESC",
                    (project_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM slow_requests ORDER BY response_time_ms DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    def log_project_access(self, project_id: str, user_name: str, action: str,
                          resource_type: str = "", resource_id: int | None = None):
        """记录项目访问日志（用于审计越权行为）"""
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO project_access_log
                   (project_id, user_name, action, resource_type, resource_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (project_id, user_name, action, resource_type, resource_id),
            )
