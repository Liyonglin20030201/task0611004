"""Node.js 日志解析器"""

from __future__ import annotations

import json
import re
from datetime import datetime

from .base import BaseParser, LogEntry

# Common Node.js log patterns
# JSON format (winston/pino): {"level":"error","message":"...","timestamp":"..."}
# Text format: 2026-06-10T10:00:00.000Z [ERROR] message
# PM2 format: 0|app  | 2026-06-10T10:00:00: message

NODE_TEXT_RE = re.compile(
    r'(?P<time>\d{4}-\d{2}-\d{2}T[\d:.]+Z?)\s+'
    r'(?:\[(?P<level>\w+)\]\s*)?'
    r'(?P<message>.*)'
)

PM2_RE = re.compile(
    r'\d+\|\S+\s+\|\s+'
    r'(?P<time>\d{4}-\d{2}-\d{2}T[\d:.]+Z?):\s*'
    r'(?P<message>.*)'
)

LEVEL_MAP = {
    "error": "error",
    "err": "error",
    "warn": "warning",
    "warning": "warning",
    "info": "info",
    "debug": "debug",
    "verbose": "debug",
    "fatal": "error",
    "silly": "debug",
}


class NodeParser(BaseParser):
    name = "node"
    description = "Node.js application log parser (winston/pino/PM2)"
    file_patterns = ["*.log", "pm2-*.log", "out.log", "err.log"]

    def parse_line(self, line: str, line_number: int = 0) -> LogEntry | None:
        line = line.strip()
        if not line:
            return None

        # Try JSON format first
        if line.startswith("{"):
            return self._parse_json(line, line_number)

        # Try PM2 format
        pm2_match = PM2_RE.match(line)
        if pm2_match:
            return self._parse_pm2(pm2_match, line, line_number)

        # Try text format
        text_match = NODE_TEXT_RE.match(line)
        if text_match:
            return self._parse_text(text_match, line, line_number)

        return None

    def _parse_json(self, line: str, line_number: int) -> LogEntry | None:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None

        level_raw = str(data.get("level", "info")).lower()
        level = LEVEL_MAP.get(level_raw, "info")

        ts = None
        for ts_key in ("timestamp", "time", "@timestamp", "ts"):
            if ts_key in data:
                ts = self._parse_timestamp(str(data[ts_key]))
                break

        message = data.get("message", data.get("msg", ""))

        metadata = {k: v for k, v in data.items()
                    if k not in ("level", "message", "msg", "timestamp", "time", "@timestamp", "ts")}

        if "responseTime" in data or "response_time" in data:
            rt = data.get("responseTime") or data.get("response_time")
            metadata["response_time_ms"] = float(rt) if rt else None

        if "statusCode" in data or "status" in data:
            metadata["status_code"] = data.get("statusCode") or data.get("status")

        return LogEntry(
            timestamp=ts,
            level=level,
            message=str(message),
            raw_line=line,
            line_number=line_number,
            metadata=metadata,
        )

    def _parse_pm2(self, match: re.Match, line: str, line_number: int) -> LogEntry | None:
        ts = self._parse_timestamp(match.group("time"))
        message = match.group("message")
        level = self._detect_level(message)

        return LogEntry(
            timestamp=ts,
            level=level,
            message=message,
            raw_line=line,
            line_number=line_number,
            metadata={},
        )

    def _parse_text(self, match: re.Match, line: str, line_number: int) -> LogEntry | None:
        ts = self._parse_timestamp(match.group("time"))
        level_raw = (match.group("level") or "").lower()
        level = LEVEL_MAP.get(level_raw, self._detect_level(match.group("message")))
        message = match.group("message")

        return LogEntry(
            timestamp=ts,
            level=level,
            message=message,
            raw_line=line,
            line_number=line_number,
            metadata={},
        )

    def _parse_timestamp(self, ts_str: str) -> datetime | None:
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                return datetime.strptime(ts_str, fmt)
            except ValueError:
                continue
        return None

    def _detect_level(self, message: str) -> str:
        msg_lower = message.lower()
        if any(w in msg_lower for w in ("error", "exception", "fatal", "uncaught")):
            return "error"
        if any(w in msg_lower for w in ("warn", "warning", "deprecated")):
            return "warning"
        return "info"
