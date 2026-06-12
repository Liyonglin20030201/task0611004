"""Python 日志解析器"""

from __future__ import annotations

import re
from datetime import datetime

from .base import BaseParser, LogEntry

# Standard Python logging format:
# 2026-06-10 10:00:00,123 - module_name - ERROR - message
# Variations:
# [2026-06-10 10:00:00] ERROR in app: message
# ERROR 2026-06-10 10:00:00 module message

PYTHON_STANDARD_RE = re.compile(
    r'(?P<time>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[,.\d]*)\s*'
    r'[-–]\s*(?P<module>\S+)\s*'
    r'[-–]\s*(?P<level>\w+)\s*'
    r'[-–]\s*(?P<message>.*)'
)

PYTHON_BRACKET_RE = re.compile(
    r'\[(?P<time>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[,.\d]*)\]\s+'
    r'(?P<level>\w+)\s+(?:in\s+\S+:\s*)?'
    r'(?P<message>.*)'
)

PYTHON_ALT_RE = re.compile(
    r'(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+'
    r'(?P<time>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[,.\d]*)\s+'
    r'(?P<module>\S+)\s+'
    r'(?P<message>.*)'
)

# Django/Flask traceback detection
TRACEBACK_START_RE = re.compile(r'^Traceback \(most recent call last\):')
EXCEPTION_RE = re.compile(r'^(\w+(?:\.\w+)*Error|\w+Exception|\w+Warning):\s*(.*)')

LEVEL_MAP = {
    "DEBUG": "debug",
    "INFO": "info",
    "WARNING": "warning",
    "WARN": "warning",
    "ERROR": "error",
    "CRITICAL": "error",
    "FATAL": "error",
}


class PythonLogParser(BaseParser):
    name = "python"
    description = "Python logging module output parser"
    file_patterns = ["*.log", "django*.log", "flask*.log", "gunicorn*.log", "celery*.log"]

    def __init__(self):
        self._in_traceback = False

    def parse_line(self, line: str, line_number: int = 0) -> LogEntry | None:
        line_stripped = line.rstrip()
        if not line_stripped:
            self._in_traceback = False
            return None

        # Traceback continuation
        if self._in_traceback:
            if EXCEPTION_RE.match(line_stripped):
                self._in_traceback = False
                match = EXCEPTION_RE.match(line_stripped)
                return LogEntry(
                    timestamp=None,
                    level="error",
                    message=line_stripped,
                    raw_line=line_stripped,
                    line_number=line_number,
                    metadata={"exception_type": match.group(1)},
                )
            return None

        # Traceback start
        if TRACEBACK_START_RE.match(line_stripped):
            self._in_traceback = True
            return LogEntry(
                timestamp=None,
                level="error",
                message="Traceback detected",
                raw_line=line_stripped,
                line_number=line_number,
                metadata={"is_traceback_start": True},
            )

        # Standard format
        match = PYTHON_STANDARD_RE.match(line_stripped)
        if match:
            return self._build_entry(match, line_stripped, line_number)

        # Bracket format
        match = PYTHON_BRACKET_RE.match(line_stripped)
        if match:
            return self._build_entry(match, line_stripped, line_number)

        # Alt format (level first)
        match = PYTHON_ALT_RE.match(line_stripped)
        if match:
            return self._build_entry(match, line_stripped, line_number)

        return None

    def _build_entry(self, match: re.Match, line: str, line_number: int) -> LogEntry:
        groups = match.groupdict()
        ts = self._parse_timestamp(groups.get("time", ""))
        level_raw = groups.get("level", "INFO").upper()
        level = LEVEL_MAP.get(level_raw, "info")
        message = groups.get("message", "")

        metadata = {}
        if "module" in groups and groups["module"]:
            metadata["module"] = groups["module"]

        # Detect response time in message
        rt_match = re.search(r'(\d+(?:\.\d+)?)\s*ms', message)
        if rt_match:
            metadata["response_time_ms"] = float(rt_match.group(1))

        return LogEntry(
            timestamp=ts,
            level=level,
            message=message,
            raw_line=line,
            line_number=line_number,
            metadata=metadata,
        )

    def _parse_timestamp(self, ts_str: str) -> datetime | None:
        ts_str = ts_str.replace(",", ".")
        for fmt in (
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                return datetime.strptime(ts_str, fmt)
            except ValueError:
                continue
        return None
