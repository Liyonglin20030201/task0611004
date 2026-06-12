"""邮件通知渠道"""

from __future__ import annotations

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from log_inspector.config import EmailNotifyConfig
from log_inspector.notifier.base import BaseNotifyChannel, NotifyEvent


class EmailChannel(BaseNotifyChannel):
    name = "email"

    def __init__(self, config: EmailNotifyConfig):
        self.config = config

    def send(self, event: NotifyEvent) -> bool:
        msg = MIMEMultipart()
        msg["From"] = self.config.from_addr
        msg["To"] = ", ".join(self.config.to_addrs)
        msg["Subject"] = f"[Log Inspector] {event.title}"
        msg.attach(MIMEText(event.body, "plain", "utf-8"))

        ssl_context = self._build_ssl_context()
        server = self._connect(ssl_context)

        try:
            password = self.config.get_password()
            if self.config.smtp_user and password:
                server.login(self.config.smtp_user, password)
            elif self.config.smtp_user and not password:
                raise ValueError(
                    "SMTP 认证配置不完整: 已设置 smtp_user 但密码为空。"
                    "请在 smtp_password 或 smtp_password_env 环境变量中提供密码"
                )
            server.sendmail(self.config.from_addr, self.config.to_addrs, msg.as_string())
            return True
        finally:
            server.quit()

    def _build_ssl_context(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context()
        if self.config.ssl_certfile:
            ctx.load_cert_chain(
                certfile=self.config.ssl_certfile,
                keyfile=self.config.ssl_keyfile or None,
            )
        return ctx

    def _connect(self, ssl_context: ssl.SSLContext) -> smtplib.SMTP:
        if self.config.use_ssl:
            server = smtplib.SMTP_SSL(
                self.config.smtp_host,
                self.config.smtp_port,
                context=ssl_context,
            )
        else:
            server = smtplib.SMTP(self.config.smtp_host, self.config.smtp_port)
            if self.config.use_tls:
                server.starttls(context=ssl_context)
        return server
