"""Webhook 通知渠道"""

from __future__ import annotations

import hashlib
import hmac
import json

import requests

from log_inspector.config import WebhookNotifyConfig
from log_inspector.notifier.base import BaseNotifyChannel, NotifyEvent


class WebhookChannel(BaseNotifyChannel):
    name = "webhook"

    def __init__(self, config: WebhookNotifyConfig):
        self.config = config

    def send(self, event: NotifyEvent) -> bool:
        payload = {
            "title": event.title,
            "level": event.level,
            "rule_name": event.rule_name,
            "message": event.message[:1000],
            "timestamp": event.timestamp.isoformat() if event.timestamp else None,
            "scan_id": event.scan_id,
            "metadata": event.metadata,
        }

        headers = dict(self.config.headers)
        headers.setdefault("Content-Type", "application/json")

        body = json.dumps(payload, ensure_ascii=False)

        if self.config.secret:
            signature = hmac.HMAC(
                self.config.secret.encode(),
                body.encode(),
                hashlib.sha256,
            ).hexdigest()
            headers["X-Signature"] = signature

        resp = requests.request(
            method=self.config.method,
            url=self.config.url,
            data=body.encode("utf-8"),
            headers=headers,
            timeout=10,
        )
        return resp.status_code < 400
