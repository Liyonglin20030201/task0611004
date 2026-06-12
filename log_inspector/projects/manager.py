"""项目管理器：CRUD 操作、配置隔离、目录结构管理"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml
from rich.console import Console

from log_inspector.config import (
    DEFAULT_CONFIG_DIR,
    ProjectConfig,
    ProjectRegistry,
    load_projects,
    Settings,
)

console = Console(stderr=True)


class ProjectManager:
    """管理多项目的配置、规则和权限"""

    def __init__(self, config_dir: Path | None = None):
        self.config_dir = config_dir or DEFAULT_CONFIG_DIR
        self._registry_path = self.config_dir / "projects.yaml"
        self._registry = load_projects(self.config_dir)

    @property
    def projects(self) -> list[ProjectConfig]:
        return self._registry.projects

    @property
    def default_project(self) -> str:
        return self._registry.default_project

    def get_project(self, project_id: str) -> ProjectConfig | None:
        for p in self._registry.projects:
            if p.project_id == project_id:
                return p
        return None

    def create_project(self, project_id: str, name: str,
                       description: str = "",
                       allowed_users: list[str] | None = None) -> ProjectConfig:
        """创建新项目，初始化目录结构"""
        if self.get_project(project_id):
            raise ValueError(f"项目已存在: {project_id}")

        project_dir = self.config_dir / project_id
        project_dir.mkdir(parents=True, exist_ok=True)

        default_settings = {
            "log_sources": [],
            "slow_request": {"warning_ms": 1000.0, "critical_ms": 5000.0},
            "auth": {"enabled": False, "allowed_users": [], "require_sudo": False},
            "database_path": f"data/{project_id}.db",
            "export_dir": "exports",
            "plugin_dir": "plugins",
            "log_dir": "logs",
            "batch_size": 10000,
        }
        default_rules = {"rules": []}
        default_tasks = {"tasks": []}

        (project_dir / "settings.yaml").write_text(
            yaml.dump(default_settings, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
        (project_dir / "rules.yaml").write_text(
            yaml.dump(default_rules, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
        (project_dir / "tasks.yaml").write_text(
            yaml.dump(default_tasks, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )

        project = ProjectConfig(
            project_id=project_id,
            name=name,
            description=description,
            config_dir=str(project_dir),
            database_path=f"data/{project_id}.db",
            allowed_users=allowed_users or [],
            active=True,
        )
        self._registry.projects.append(project)
        self._save_registry()

        console.print(f"[green]项目创建成功: {project_id}[/green]")
        return project

    def delete_project(self, project_id: str, remove_files: bool = False):
        """删除项目"""
        project = self.get_project(project_id)
        if not project:
            raise ValueError(f"项目不存在: {project_id}")
        if project_id == self._registry.default_project:
            raise ValueError("不能删除默认项目")

        self._registry.projects = [
            p for p in self._registry.projects if p.project_id != project_id
        ]
        self._save_registry()

        if remove_files and project.config_dir:
            project_dir = Path(project.config_dir)
            if project_dir.exists():
                shutil.rmtree(project_dir)

        console.print(f"[yellow]项目已删除: {project_id}[/yellow]")

    def switch_default(self, project_id: str):
        """切换默认项目"""
        if not self.get_project(project_id):
            raise ValueError(f"项目不存在: {project_id}")
        self._registry.default_project = project_id
        self._save_registry()
        console.print(f"[green]默认项目已切换到: {project_id}[/green]")

    def get_project_config_dir(self, project_id: str) -> Path | None:
        """获取项目的配置目录"""
        project = self.get_project(project_id)
        if project and project.config_dir:
            return Path(project.config_dir)
        return None

    def _save_registry(self):
        """保存项目注册表到 YAML"""
        data = {
            "default_project": self._registry.default_project,
            "projects": [p.model_dump() for p in self._registry.projects],
        }
        self._registry_path.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
