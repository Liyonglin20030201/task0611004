"""通知分发器：路由事件到各渠道，实现冷却去重"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from rich.console import Console

from log_inspector.config import NotificationConfig, RuleConfig
from log_inspector.notifier.base import BaseNotifyChannel, NotifyEvent

console = Console(stderr=True)

LEVEL_PRIORITY = {"info": 0, "warning": 1, "error": 2, "critical": 3}


class NotificationDispatcher:
    def __init__(self, config: NotificationConfig):
        self.config = config
        self._channels: dict[str, BaseNotifyChannel] = {}
        self._cooldown_map: dict[str, float] = {}
        self._init_channels()

    def _init_channels(self):
        if not self.config.enabled:
            return

        if "email" in self.config.channels and self.config.email.enabled:
            from log_inspector.notifier.email_channel import EmailChannel
            self._channels["email"] = EmailChannel(self.config.email)

        if "webhook" in self.config.channels and self.config.webhook.enabled:
            from log_inspector.notifier.webhook_channel import WebhookChannel
            self._channels["webhook"] = WebhookChannel(self.config.webhook)

        if "dingtalk" in self.config.channels and self.config.dingtalk.enabled:
            from log_inspector.notifier.dingtalk_channel import DingTalkChannel
            self._channels["dingtalk"] = DingTalkChannel(self.config.dingtalk)

    def should_notify(self, event: NotifyEvent, rule: RuleConfig | None = None) -> bool:
        if not self.config.enabled:
            return False

        event_level = LEVEL_PRIORITY.get(event.level, 0)
        min_level = LEVEL_PRIORITY.get(self.config.min_level, 2)
        if event_level < min_level:
            return False

        if rule and not rule.notify:
            return False

        dedup_key = self._dedup_key(event)
        now = time.time()
        last_sent = self._cooldown_map.get(dedup_key, 0)
        if now - last_sent < self.config.cooldown_seconds:
            return False

        return True

    def dispatch(self, event: NotifyEvent, rule: RuleConfig | None = None) -> list[str]:
        """分发通知到所有配置的渠道，返回成功发送的渠道列表"""
        if not self.should_notify(event, rule):
            return []

        channels_to_use = self.config.channels
        if rule and rule.notify_channels:
            channels_to_use = rule.notify_channels

        sent_channels: list[str] = []
        for channel_name in channels_to_use:
            channel = self._channels.get(channel_name)
            if channel is None:
                continue
            try:
                if channel.send(event):
                    sent_channels.append(channel_name)
            except Exception as e:
                console.print(f"[red]通知发送失败 [{channel_name}]: {e}[/red]")

        if sent_channels:
            dedup_key = self._dedup_key(event)
            self._cooldown_map[dedup_key] = time.time()

        return sent_channels

    def _dedup_key(self, event: NotifyEvent) -> str:
        raw = f"{event.rule_name}:{event.message[:100]}"
        return hashlib.md5(raw.encode()).hexdigest()
