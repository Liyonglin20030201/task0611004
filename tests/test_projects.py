"""多项目管理测试"""

import getpass
from pathlib import Path
from unittest.mock import patch

import pytest

from log_inspector.config import ProjectConfig, ProjectRegistry, Settings
from log_inspector.db import Database
from log_inspector.projects.manager import ProjectManager
from log_inspector.projects.context import (
    ProjectContext, get_current_project, set_current_project,
)


class TestProjectContext:
    def test_default_project(self):
        set_current_project("default")
        assert get_current_project() == "default"

    def test_set_project(self):
        set_current_project("project-alpha")
        assert get_current_project() == "project-alpha"
        set_current_project("default")

    def test_context_manager(self):
        assert get_current_project() == "default"
        with ProjectContext("project-beta"):
            assert get_current_project() == "project-beta"
        assert get_current_project() == "default"


class TestProjectManager:
    def test_create_project(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "projects.yaml").write_text(
            "default_project: default\nprojects: []\n", encoding="utf-8"
        )

        manager = ProjectManager(config_dir)
        project = manager.create_project("alpha", "Alpha Project", "Test project")

        assert project.project_id == "alpha"
        assert project.name == "Alpha Project"
        assert (config_dir / "alpha" / "settings.yaml").exists()
        assert (config_dir / "alpha" / "rules.yaml").exists()
        assert (config_dir / "alpha" / "tasks.yaml").exists()

    def test_create_duplicate_project(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "projects.yaml").write_text(
            "default_project: default\nprojects:\n  - project_id: alpha\n    name: Alpha\n",
            encoding="utf-8",
        )

        manager = ProjectManager(config_dir)
        with pytest.raises(ValueError, match="项目已存在"):
            manager.create_project("alpha", "Alpha Again")

    def test_get_project(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "projects.yaml").write_text(
            "default_project: default\nprojects:\n"
            "  - project_id: beta\n    name: Beta\n    config_dir: ''\n    active: true\n",
            encoding="utf-8",
        )

        manager = ProjectManager(config_dir)
        project = manager.get_project("beta")
        assert project is not None
        assert project.name == "Beta"

    def test_get_nonexistent_project(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "projects.yaml").write_text(
            "default_project: default\nprojects: []\n", encoding="utf-8"
        )

        manager = ProjectManager(config_dir)
        assert manager.get_project("no-such") is None

    def test_delete_project(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "projects.yaml").write_text(
            "default_project: default\nprojects:\n"
            "  - project_id: to-delete\n    name: ToDelete\n    config_dir: ''\n    active: true\n",
            encoding="utf-8",
        )

        manager = ProjectManager(config_dir)
        manager.delete_project("to-delete")
        assert manager.get_project("to-delete") is None

    def test_delete_default_project_fails(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "projects.yaml").write_text(
            "default_project: default\nprojects:\n"
            "  - project_id: default\n    name: Default\n    config_dir: ''\n    active: true\n",
            encoding="utf-8",
        )

        manager = ProjectManager(config_dir)
        with pytest.raises(ValueError, match="不能删除默认项目"):
            manager.delete_project("default")

    def test_switch_default(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "projects.yaml").write_text(
            "default_project: default\nprojects:\n"
            "  - project_id: default\n    name: Default\n    config_dir: ''\n    active: true\n"
            "  - project_id: other\n    name: Other\n    config_dir: ''\n    active: true\n",
            encoding="utf-8",
        )

        manager = ProjectManager(config_dir)
        manager.switch_default("other")
        assert manager.default_project == "other"


class TestProjectPermission:
    def test_check_project_permission_allowed(self):
        from log_inspector.auth import check_project_permission
        current_user = getpass.getuser()
        assert check_project_permission("test", [current_user]) is True

    def test_check_project_permission_denied(self):
        from log_inspector.auth import check_project_permission
        assert check_project_permission("test", ["other_user_xyz"]) is False

    def test_check_project_permission_empty_allows_all(self):
        from log_inspector.auth import check_project_permission
        assert check_project_permission("test", []) is True


class TestDatabaseProjectIsolation:
    def test_scans_with_project_id(self, tmp_path):
        db = Database(tmp_path / "test.db")

        scan_a = db.create_scan("/log/a.log", "nginx", project_id="project-a")
        scan_b = db.create_scan("/log/b.log", "nginx", project_id="project-b")

        scans_a = db.list_scans(project_id="project-a")
        scans_b = db.list_scans(project_id="project-b")

        assert len(scans_a) == 1
        assert scans_a[0]["log_path"] == "/log/a.log"
        assert len(scans_b) == 1
        assert scans_b[0]["log_path"] == "/log/b.log"

    def test_list_all_scans_without_filter(self, tmp_path):
        db = Database(tmp_path / "test.db")

        db.create_scan("/log/a.log", "nginx", project_id="project-a")
        db.create_scan("/log/b.log", "nginx", project_id="project-b")

        all_scans = db.list_scans()
        assert len(all_scans) == 2
