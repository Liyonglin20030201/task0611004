"""实时监控模式"""

from log_inspector.watcher.tail import FileTailer
from log_inspector.watcher.monitor import RealtimeMonitor

__all__ = ["FileTailer", "RealtimeMonitor"]
