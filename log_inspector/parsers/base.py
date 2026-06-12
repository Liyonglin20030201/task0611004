"""日志解析器基类 - 插件接口"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional


@dataclass
class LogEntry:
    """解析后的单条日志记录"""
    timestamp: Optional[datetime] = None
    level: str = "info"
    message: str = ""
    raw_line: str = ""
    line_number: int = 0
    metadata: dict = field(default_factory=dict)


class BaseParser(ABC):
    """解析器基类，所有解析器（内置和插件）必须继承此类"""

    name: str = "base"
    description: str = "Base parser"
    file_patterns: List[str] = []

    @abstractmethod
    def parse_line(self, line: str, line_number: int = 0) -> Optional[LogEntry]:
        """解析单行日志，返回 LogEntry 或 None（无法解析时）"""
        ...

    def can_parse(self, sample_lines: List[str]) -> bool:
        """根据样本行判断是否能解析该日志格式"""
        if not sample_lines:
            return False
        parsed = 0
        for line in sample_lines[:10]:
            if self.parse_line(line) is not None:
                parsed += 1
        return parsed > len(sample_lines[:10]) * 0.5
