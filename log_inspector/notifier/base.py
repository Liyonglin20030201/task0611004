"""通知渠道基类与事件定义"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class NotifyEvent:
    rule_name: str
    level: str
    message: str
    scan_id: int | None = None
    timestamp: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def title(self) -> str:
        return f"[{self.level.upper()}] {self.rule_name}"

    @property
    def body(self) -> str:
        ts = self.timestamp.strftime("%Y-%m-%d %H:%M:%S") if self.timestamp else "unknown"
        return f"时间: {ts}\n规则: {self.rule_name}\n级别: {self.level}\n详情: {self.message[:500]}"


class BaseNotifyChannel(ABC):
    name: str = "base"

    @abstractmethod
    def send(self, event: NotifyEvent) -> bool:
        """发送通知，返回是否成功"""
        ...
