"""示例插件：自定义 Apache 日志解析器

将此文件放在 plugins/ 目录下即可自动加载。
自定义解析器必须继承 BaseParser 并实现 parse_line 方法。
"""

from __future__ import annotations

import re
from datetime import datetime

from log_inspector.parsers.base import BaseParser, LogEntry

APACHE_RE = re.compile(
    r'(?P<ip>\S+)\s+\S+\s+\S+\s+'
    r'\[(?P<time>[^\]]+)\]\s+'
    r'"(?P<method>\S+)\s+(?P<path>\S+)\s+\S+"\s+'
    r'(?P<status>\d{3})\s+'
    r'(?P<size>\d+|-)'
)


class ApacheParser(BaseParser):
    name = "apache"
    description = "Apache access log parser (插件示例)"
    file_patterns = ["apache*.log", "httpd*.log"]

    def parse_line(self, line: str, line_number: int = 0) -> LogEntry | None:
        line = line.strip()
        if not line:
            return None

        match = APACHE_RE.match(line)
        if not match:
            return None

        groups = match.groupdict()
        try:
            ts = datetime.strptime(groups["time"], "%d/%b/%Y:%H:%M:%S %z")
        except (ValueError, TypeError):
            ts = None

        status = int(groups.get("status", 0))
        level = "error" if status >= 500 else "warning" if status >= 400 else "info"

        return LogEntry(
            timestamp=ts,
            level=level,
            message=f"{groups.get('method')} {groups.get('path')} → {status}",
            raw_line=line,
            line_number=line_number,
            metadata={
                "ip": groups.get("ip"),
                "method": groups.get("method"),
                "path": groups.get("path"),
                "status_code": status,
            },
        )
