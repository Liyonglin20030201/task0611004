"""YAML 配置加载与 Pydantic 校验"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional, List

import yaml
from pydantic import BaseModel, Field, ValidationError
from rich.console import Console

console = Console(stderr=True)

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


class LogSource(BaseModel):
    path: str
    parser: str = "auto"
    encoding: str = "utf-8"


class SlowRequestThreshold(BaseModel):
    warning_ms: float = 1000.0
    critical_ms: float = 5000.0


class RuleConfig(BaseModel):
    name: str
    type: str = Field(description="regex | threshold | keyword")
    pattern: str = ""
    threshold: Optional[float] = None
    level: str = "warning"
    priority: int = 0
    scope: str = "*"
    action: str = "alert"
    enabled: bool = True
    notify: bool = True
    notify_channels: list[str] = Field(default_factory=list)


class TaskConfig(BaseModel):
    name: str
    cron: str
    log_sources: list[str]
    rules: list[str] = Field(default_factory=list)
    enabled: bool = True


class AuthConfig(BaseModel):
    enabled: bool = False
    allowed_users: list[str] = Field(default_factory=list)
    require_sudo: bool = False


# ─── Notification Config ────────────────────────────────────────────────────


class EmailNotifyConfig(BaseModel):
    enabled: bool = False
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_password_env: str = ""
    use_tls: bool = True
    use_ssl: bool = False
    ssl_certfile: str = ""
    ssl_keyfile: str = ""
    from_addr: str = ""
    to_addrs: list[str] = Field(default_factory=list)

    def get_password(self) -> str:
        """优先从环境变量获取密码，防止明文泄露"""
        import os
        if self.smtp_password_env:
            return os.environ.get(self.smtp_password_env, "")
        return self.smtp_password


class WebhookNotifyConfig(BaseModel):
    enabled: bool = False
    url: str = ""
    method: str = "POST"
    headers: dict[str, str] = Field(default_factory=dict)
    secret: str = ""


class DingTalkNotifyConfig(BaseModel):
    enabled: bool = False
    webhook_url: str = ""
    secret: str = ""


class NotificationConfig(BaseModel):
    enabled: bool = False
    min_level: str = "error"
    cooldown_seconds: int = 300
    channels: list[str] = Field(default_factory=list)
    email: EmailNotifyConfig = Field(default_factory=EmailNotifyConfig)
    webhook: WebhookNotifyConfig = Field(default_factory=WebhookNotifyConfig)
    dingtalk: DingTalkNotifyConfig = Field(default_factory=DingTalkNotifyConfig)


# ─── Watch Config ───────────────────────────────────────────────────────────


class WatchConfig(BaseModel):
    poll_interval_ms: int = 500
    buffer_size: int = 8192
    max_lines_per_second: int = 10000
    show_unmatched: bool = False
    highlight_rules: bool = True


# ─── Remote Source Config ───────────────────────────────────────────────────


class SSHCredential(BaseModel):
    host: str = ""
    port: int = 22
    username: str = ""
    password: str = ""
    key_file: str = ""
    passphrase: str = ""
    force_tls: bool = True
    host_key_verify: bool = True
    ca_cert: str = ""


class S3Credential(BaseModel):
    endpoint_url: str = ""
    region: str = ""
    bucket: str = ""
    prefix: str = ""
    access_key: str = ""
    secret_key: str = ""
    use_ssl: bool = True
    verify_ssl: bool = True
    ca_bundle: str = ""


class RemoteLogSource(BaseModel):
    name: str
    type: str = Field(description="ssh | s3")
    ssh: Optional[SSHCredential] = None
    s3: Optional[S3Credential] = None
    remote_path: str = ""
    parser: str = "auto"
    encoding: str = "utf-8"
    download_dir: str = ""


# ─── Project Config ─────────────────────────────────────────────────────────


class ProjectConfig(BaseModel):
    project_id: str
    name: str
    description: str = ""
    config_dir: str = ""
    database_path: str = ""
    allowed_users: list[str] = Field(default_factory=list)
    active: bool = True


class ProjectRegistry(BaseModel):
    default_project: str = "default"
    projects: list[ProjectConfig] = Field(default_factory=list)


# ─── Settings ───────────────────────────────────────────────────────────────


class Settings(BaseModel):
    log_sources: list[LogSource] = Field(default_factory=list)
    slow_request: SlowRequestThreshold = Field(default_factory=SlowRequestThreshold)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    notification: NotificationConfig = Field(default_factory=NotificationConfig)
    watch: WatchConfig = Field(default_factory=WatchConfig)
    remote_sources: list[RemoteLogSource] = Field(default_factory=list)
    key_store_path: str = ""
    database_path: str = "data/log_inspector.db"
    export_dir: str = "exports"
    plugin_dir: str = "plugins"
    log_dir: str = "logs"
    batch_size: int = 10000


class RulesFile(BaseModel):
    rules: list[RuleConfig] = Field(default_factory=list)


class TasksFile(BaseModel):
    tasks: list[TaskConfig] = Field(default_factory=list)


def load_yaml(path: Path) -> dict[str, Any]:
    """加载 YAML 文件，提供清晰的错误信息"""
    if not path.exists():
        console.print(f"[red]配置文件不存在: {path}[/red]")
        sys.exit(1)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if data is not None else {}
    except yaml.YAMLError as e:
        msg = f"YAML 解析错误: {path}\n"
        if hasattr(e, "problem_mark"):
            mark = e.problem_mark
            msg += f"  位置: 第 {mark.line + 1} 行, 第 {mark.column + 1} 列\n"
        if hasattr(e, "problem"):
            msg += f"  原因: {e.problem}\n"
        if hasattr(e, "context"):
            msg += f"  上下文: {e.context}\n"
        console.print(f"[red]{msg}[/red]")
        sys.exit(1)


def validate_config(data: dict[str, Any], model: type[BaseModel], source: str = "") -> BaseModel:
    """用 Pydantic 校验配置数据，校验失败时输出详细错误"""
    try:
        return model.model_validate(data)
    except ValidationError as e:
        console.print(f"[red]配置校验失败{f' ({source})' if source else ''}:[/red]")
        for err in e.errors():
            loc = " → ".join(str(x) for x in err["loc"])
            console.print(f"  [yellow]字段:[/yellow] {loc}")
            console.print(f"  [yellow]错误:[/yellow] {err['msg']}")
            if err.get("input") is not None:
                console.print(f"  [yellow]实际值:[/yellow] {err['input']}")
            console.print()
        sys.exit(1)


def load_settings(config_dir: Path | None = None) -> Settings:
    config_dir = config_dir or DEFAULT_CONFIG_DIR
    data = load_yaml(config_dir / "settings.yaml")
    return validate_config(data, Settings, "settings.yaml")


def load_rules(config_dir: Path | None = None) -> list[RuleConfig]:
    config_dir = config_dir or DEFAULT_CONFIG_DIR
    data = load_yaml(config_dir / "rules.yaml")
    rules_file = validate_config(data, RulesFile, "rules.yaml")
    return rules_file.rules


def load_tasks(config_dir: Path | None = None) -> list[TaskConfig]:
    config_dir = config_dir or DEFAULT_CONFIG_DIR
    data = load_yaml(config_dir / "tasks.yaml")
    tasks_file = validate_config(data, TasksFile, "tasks.yaml")
    return tasks_file.tasks


def load_projects(config_dir: Path | None = None) -> ProjectRegistry:
    config_dir = config_dir or DEFAULT_CONFIG_DIR
    path = config_dir / "projects.yaml"
    if not path.exists():
        return ProjectRegistry()
    data = load_yaml(path)
    return validate_config(data, ProjectRegistry, "projects.yaml")


# ─── 非中断式校验（供 config check 使用） ────────────────────────────────────


def try_load_yaml(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    """加载 YAML，不中断。返回 (data, errors)。"""
    errors: list[str] = []
    if not path.exists():
        errors.append(f"文件不存在: {path}")
        return None, errors
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return (data if data is not None else {}), []
    except yaml.YAMLError as e:
        msg = f"YAML 语法错误:"
        if hasattr(e, "problem_mark"):
            mark = e.problem_mark
            msg += f" 第 {mark.line + 1} 行, 第 {mark.column + 1} 列"
        if hasattr(e, "problem"):
            msg += f"\n  原因: {e.problem}"
        if hasattr(e, "context") and e.context:
            msg += f"\n  上下文: {e.context}"
        errors.append(msg)
        return None, errors


def try_validate_config(data: dict[str, Any], model: type[BaseModel]) -> tuple[BaseModel | None, list[str]]:
    """用 Pydantic 校验，不中断。返回 (result, errors)。"""
    errors: list[str] = []
    try:
        return model.model_validate(data), []
    except ValidationError as e:
        for err in e.errors():
            loc_parts = [str(x) for x in err["loc"]] if err["loc"] else ["(root)"]
            loc = " → ".join(loc_parts)
            line = f"字段 [{loc}]: {err['msg']}"
            if err.get("input") is not None:
                line += f" (实际值: {err['input']})"
            errors.append(line)
        return None, errors
