"""权限校验模块"""

from __future__ import annotations

import getpass
import os
import sys

from rich.console import Console

from log_inspector.config import AuthConfig

console = Console(stderr=True)


def check_permission(auth_config: AuthConfig) -> bool:
    """执行权限校验，返回是否通过"""
    if not auth_config.enabled:
        return True

    current_user = getpass.getuser()

    if auth_config.allowed_users and current_user not in auth_config.allowed_users:
        console.print(
            f"[red]权限不足: 用户 '{current_user}' 不在允许列表中[/red]\n"
            f"  允许的用户: {', '.join(auth_config.allowed_users)}"
        )
        return False

    if auth_config.require_sudo:
        if os.name == "nt":
            try:
                import ctypes
                is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
            except Exception:
                is_admin = False
            if not is_admin:
                console.print("[red]权限不足: 需要管理员权限运行[/red]")
                return False
        else:
            if os.geteuid() != 0:
                console.print("[red]权限不足: 需要 sudo 权限运行[/red]")
                return False

    return True


def require_permission(auth_config: AuthConfig):
    """校验权限，不通过则退出"""
    if not check_permission(auth_config):
        sys.exit(1)


def check_project_permission(project_id: str, allowed_users: list[str]) -> bool:
    """项目级权限校验"""
    if not allowed_users:
        return True
    current_user = getpass.getuser()
    if current_user not in allowed_users:
        console.print(
            f"[red]项目权限不足: 用户 '{current_user}' 无权访问项目 '{project_id}'[/red]"
        )
        return False
    return True


def validate_ssh_key(key_path: str) -> tuple[bool, str]:
    """校验 SSH 密钥文件（委托给 remote.key_manager）"""
    from log_inspector.remote.key_manager import validate_ssh_key as _validate
    return _validate(key_path)
