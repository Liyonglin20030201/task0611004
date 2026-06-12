"""多项目管理模块"""

from log_inspector.projects.manager import ProjectManager
from log_inspector.projects.context import ProjectContext, get_current_project, set_current_project

__all__ = ["ProjectManager", "ProjectContext", "get_current_project", "set_current_project"]
