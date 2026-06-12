"""项目上下文管理：线程本地存储当前活动项目"""

from __future__ import annotations

import threading

_context = threading.local()


class ProjectContext:
    """项目上下文"""

    def __init__(self, project_id: str = "default"):
        self.project_id = project_id

    def __enter__(self):
        set_current_project(self.project_id)
        return self

    def __exit__(self, *args):
        set_current_project("default")


def get_current_project() -> str:
    return getattr(_context, "project_id", "default")


def set_current_project(project_id: str):
    _context.project_id = project_id
