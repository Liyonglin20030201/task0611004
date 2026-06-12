"""数据库迁移管理"""

from __future__ import annotations

MIGRATIONS: list[tuple[str, str]] = [
    (
        "001_add_notifications_table",
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER REFERENCES scans(id),
            rule_name TEXT,
            channel TEXT,
            status TEXT DEFAULT 'sent',
            sent_at TEXT DEFAULT (datetime('now')),
            error_message TEXT
        );
        """,
    ),
    (
        "002_add_watch_sessions_table",
        """
        CREATE TABLE IF NOT EXISTS watch_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_path TEXT NOT NULL,
            started_at TEXT DEFAULT (datetime('now')),
            stopped_at TEXT,
            total_lines INTEGER DEFAULT 0,
            matched_lines INTEGER DEFAULT 0,
            status TEXT DEFAULT 'running'
        );
        """,
    ),
    (
        "003_add_source_columns_to_scans",
        """
        ALTER TABLE scans ADD COLUMN source_type TEXT DEFAULT 'local';
        """,
    ),
    (
        "004_add_source_name_to_scans",
        """
        ALTER TABLE scans ADD COLUMN source_name TEXT DEFAULT '';
        """,
    ),
    (
        "005_add_project_id_to_scans",
        """
        ALTER TABLE scans ADD COLUMN project_id TEXT DEFAULT 'default';
        """,
    ),
    (
        "006_add_project_id_to_findings",
        """
        ALTER TABLE findings ADD COLUMN project_id TEXT DEFAULT 'default';
        """,
    ),
    (
        "007_add_project_id_to_slow_requests",
        """
        ALTER TABLE slow_requests ADD COLUMN project_id TEXT DEFAULT 'default';
        """,
    ),
    (
        "008_add_project_id_to_exports",
        """
        ALTER TABLE exports ADD COLUMN project_id TEXT DEFAULT 'default';
        """,
    ),
    (
        "009_add_project_id_to_schedule_runs",
        """
        ALTER TABLE schedule_runs ADD COLUMN project_id TEXT DEFAULT 'default';
        """,
    ),
    (
        "010_add_project_indexes",
        """
        CREATE INDEX IF NOT EXISTS idx_scans_project ON scans(project_id);
        CREATE INDEX IF NOT EXISTS idx_findings_project ON findings(project_id);
        CREATE INDEX IF NOT EXISTS idx_slow_requests_project ON slow_requests(project_id);
        """,
    ),
    (
        "011_add_projects_table_and_fk",
        """
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            allowed_users TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );
        INSERT OR IGNORE INTO projects (project_id, name) VALUES ('default', '默认项目');
        """,
    ),
    (
        "012_add_project_access_log",
        """
        CREATE TABLE IF NOT EXISTS project_access_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            user_name TEXT NOT NULL,
            action TEXT NOT NULL,
            resource_type TEXT,
            resource_id INTEGER,
            accessed_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_access_log_project ON project_access_log(project_id);
        CREATE INDEX IF NOT EXISTS idx_access_log_user ON project_access_log(user_name);
        """,
    ),
    (
        "013_add_findings_project_fk_trigger",
        """
        CREATE TRIGGER IF NOT EXISTS fk_findings_project_insert
        BEFORE INSERT ON findings
        WHEN NEW.project_id != 'default'
        BEGIN
            SELECT RAISE(ABORT, '项目不存在，拒绝插入')
            WHERE NOT EXISTS (SELECT 1 FROM projects WHERE project_id = NEW.project_id);
        END;
        CREATE TRIGGER IF NOT EXISTS fk_scans_project_insert
        BEFORE INSERT ON scans
        WHEN NEW.project_id != 'default'
        BEGIN
            SELECT RAISE(ABORT, '项目不存在，拒绝插入')
            WHERE NOT EXISTS (SELECT 1 FROM projects WHERE project_id = NEW.project_id);
        END;
        CREATE TRIGGER IF NOT EXISTS fk_slow_requests_project_insert
        BEFORE INSERT ON slow_requests
        WHEN NEW.project_id != 'default'
        BEGIN
            SELECT RAISE(ABORT, '项目不存在，拒绝插入')
            WHERE NOT EXISTS (SELECT 1 FROM projects WHERE project_id = NEW.project_id);
        END;
        """,
    ),
]
