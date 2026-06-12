"""Nginx 日志解析器"""

from __future__ import annotations

import re
from datetime import datetime

from .base import BaseParser, LogEntry

# Nginx combined log format:
# 192.168.1.1 - - [10/Jun/2026:10:00:00 +0800] "GET /api/users HTTP/1.1" 200 1234 "-" "Mozilla/5.0"
NGINX_COMBINED_RE = re.compile(
    r'(?P<ip>\S+)\s+\S+\s+\S+\s+'
    r'\[(?P<time>[^\]]+)\]\s+'
    r'"(?P<method>\S+)\s+(?P<path>\S+)\s+\S+"\s+'
    r'(?P<status>\d{3})\s+'
    r'(?P<size>\d+|-)\s*'
    r'(?:"(?P<referer>[^"]*)"\s*)?'
    r'(?:"(?P<ua>[^"]*)")?'
    r'(?:\s+(?P<response_time>[\d.]+))?'
)

NGINX_TIME_FORMAT = "%d/%b/%Y:%H:%M:%S %z"


class NginxParser(BaseParser):
    name = "nginx"
    description = "Nginx access/error log parser"
    file_patterns = ["access.log*", "nginx*.log", "error.log*"]

    def parse_line(self, line: str, line_number: int = 0) -> LogEntry | None:
        line = line.strip()
        if not line:
            return None

        match = NGINX_COMBINED_RE.match(line)
        if not match:
            return self._parse_error_log(line, line_number)

        groups = match.groupdict()
        try:
            ts = datetime.strptime(groups["time"], NGINX_TIME_FORMAT)
        except (ValueError, TypeError):
            ts = None

        status = int(groups.get("status", 0))
        level = "error" if status >= 500 else "warning" if status >= 400 else "info"

        response_time = None
        if groups.get("response_time"):
            try:
                response_time = float(groups["response_time"]) * 1000
            except ValueError:
                pass

        metadata = {
            "ip": groups.get("ip"),
            "method": groups.get("method"),
            "path": groups.get("path"),
            "status_code": status,
            "size": int(groups["size"]) if groups.get("size", "-") != "-" else 0,
        }
        if response_time is not None:
            metadata["response_time_ms"] = response_time

        return LogEntry(
            timestamp=ts,
            level=level,
            message=f"{groups.get('method')} {groups.get('path')} → {status}",
            raw_line=line,
            line_number=line_number,
            metadata=metadata,
        )

    def _parse_error_log(self, line: str, line_number: int) -> LogEntry | None:
        # Nginx error log: 2026/06/10 10:00:00 [error] ...
        error_re = re.match(
            r'(\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})\s+\[(\w+)\]\s+(.*)',
            line,
        )
        if not error_re:
            return None

        try:
            ts = datetime.strptime(error_re.group(1), "%Y/%m/%d %H:%M:%S")
        except ValueError:
            ts = None

        return LogEntry(
            timestamp=ts,
            level=error_re.group(2),
            message=error_re.group(3),
            raw_line=line,
            line_number=line_number,
            metadata={},
        )
