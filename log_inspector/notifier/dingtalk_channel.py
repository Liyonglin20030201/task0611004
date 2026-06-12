"""钉钉机器人通知渠道"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.parse

import requests

from log_inspector.config import DingTalkNotifyConfig
from log_inspector.notifier.base import BaseNotifyChannel, NotifyEvent


class DingTalkChannel(BaseNotifyChannel):
    name = "dingtalk"

    def __init__(self, config: DingTalkNotifyConfig):
        self.config = config

    def send(self, event: NotifyEvent) -> bool:
        url = self._sign_url()
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": event.title,
                "text": (
                    f"### {event.title}\n\n"
                    f"- **规则**: {event.rule_name}\n"
                    f"- **级别**: {event.level}\n"
                    f"- **时间**: {event.timestamp.strftime('%Y-%m-%d %H:%M:%S') if event.timestamp else '-'}\n"
                    f"- **详情**: {event.message[:500]}\n"
                ),
            },
        }

        resp = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("errcode", -1) == 0
        return False

    def _sign_url(self) -> str:
        if not self.config.secret:
            return self.config.webhook_url

        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{self.config.secret}"
        hmac_code = hmac.HMAC(
            self.config.secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        return f"{self.config.webhook_url}&timestamp={timestamp}&sign={sign}"
