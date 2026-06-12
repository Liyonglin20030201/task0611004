"""实时监控器：编排 tailer + parser + rule engine"""

from __future__ import annotations

import signal
import time as _time
from datetime import datetime
from pathlib import Path
from typing import Callable

from rich.console import Console

from log_inspector.config import Settings, RuleConfig, WatchConfig
from log_inspector.db import Database
from log_inspector.notifier import NotificationDispatcher, NotifyEvent
from log_inspector.parsers.base import BaseParser, LogEntry
from log_inspector.rules.engine import RuleEngine
from log_inspector.watcher.tail import FileTailer

console = Console(stderr=True)

_BATCH_WINDOW_SECONDS = 5.0


class RealtimeMonitor:
    """实时监控日志文件并即时匹配规则"""

    def __init__(
        self,
        db: Database,
        settings: Settings,
        parser: BaseParser,
        rules: list[RuleConfig],
        rule_names: list[str] | None = None,
        notifier: NotificationDispatcher | None = None,
        on_match: Callable[[LogEntry, list[RuleConfig]], None] | None = None,
    ):
        self.db = db
        self.settings = settings
        self.parser = parser
        self.engine = RuleEngine(rules)
        self.rule_names = rule_names
        self._notifier = notifier
        self._on_match = on_match
        self._running = False
        self._total_lines = 0
        self._matched_lines = 0
        self._session_id: int | None = None
        self._batch_window_sec = _BATCH_WINDOW_SECONDS
        self._window_entries: list[LogEntry] = []
        self._window_start: float = 0.0

    def start(self, log_path: Path, from_end: bool = True):
        """启动实时监控，阻塞直到收到停止信号"""
        self._running = True
        self._session_id = self.db.create_watch_session(str(log_path))
        self._window_start = _time.monotonic()

        tailer = FileTailer(
            log_path,
            poll_interval_ms=self.settings.watch.poll_interval_ms,
            from_end=from_end,
        )

        self._setup_signal_handlers()
        console.print(f"[green]开始监控: {log_path}[/green] (Ctrl+C 停止)")

        try:
            for line in tailer.follow():
                if not self._running:
                    break
                self._process_line(line)
                self._maybe_flush_window()
        except KeyboardInterrupt:
            pass
        finally:
            self._flush_window()
            self._stop()

    def stop(self):
        self._running = False

    def _stop(self):
        self._running = False
        if self._session_id:
            self.db.update_watch_session(
                self._session_id, "stopped",
                self._total_lines, self._matched_lines,
            )
        console.print(
            f"\n[yellow]监控已停止:[/yellow] {self._total_lines} 行已处理, "
            f"{self._matched_lines} 条匹配"
        )

    def _setup_signal_handlers(self):
        def _handler(signum, frame):
            self._running = False

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)

    def _process_line(self, line: str):
        self._total_lines += 1
        entry = self.parser.parse_line(line, self._total_lines)
        if entry is None:
            return

        matched_rules = self.engine.match(entry, self.rule_names)
        if matched_rules:
            self._matched_lines += 1
            self._window_entries.append(entry)

            if self._on_match:
                self._on_match(entry, matched_rules)

            if self._notifier:
                for rule in matched_rules:
                    if rule.notify:
                        event = NotifyEvent(
                            rule_name=rule.name,
                            level=rule.level,
                            message=entry.message,
                            timestamp=entry.timestamp,
                            metadata=entry.metadata,
                        )
                        self._notifier.dispatch(event, rule)

    def _maybe_flush_window(self):
        """基于时间窗口的批次内存释放"""
        now = _time.monotonic()
        if now - self._window_start >= self._batch_window_sec:
            self._flush_window()

    def _flush_window(self):
        """释放当前时间窗口的缓存条目"""
        self._window_entries.clear()
        self._window_start = _time.monotonic()
