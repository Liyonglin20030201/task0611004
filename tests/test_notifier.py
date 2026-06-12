"""通知系统测试"""

import time
from unittest.mock import patch, MagicMock

import pytest

from log_inspector.config import (
    NotificationConfig, EmailNotifyConfig, WebhookNotifyConfig,
    DingTalkNotifyConfig, RuleConfig,
)
from log_inspector.notifier import NotificationDispatcher, NotifyEvent
from log_inspector.notifier.base import NotifyEvent
from log_inspector.notifier.email_channel import EmailChannel
from log_inspector.notifier.webhook_channel import WebhookChannel
from log_inspector.notifier.dingtalk_channel import DingTalkChannel


class TestNotifyEvent:
    def test_title(self):
        event = NotifyEvent(rule_name="test_rule", level="error", message="Something failed")
        assert event.title == "[ERROR] test_rule"

    def test_body(self):
        event = NotifyEvent(rule_name="test_rule", level="error", message="Something failed")
        assert "test_rule" in event.body
        assert "error" in event.body


class TestEmailChannel:
    @patch("log_inspector.notifier.email_channel.smtplib.SMTP")
    def test_send_success(self, mock_smtp_class):
        mock_server = MagicMock()
        mock_smtp_class.return_value = mock_server

        config = EmailNotifyConfig(
            enabled=True,
            smtp_host="smtp.test.com",
            smtp_port=587,
            smtp_user="user",
            smtp_password="pass",
            use_tls=True,
            from_addr="from@test.com",
            to_addrs=["to@test.com"],
        )
        channel = EmailChannel(config)
        event = NotifyEvent(rule_name="test", level="error", message="Test message")

        result = channel.send(event)
        assert result is True
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("user", "pass")
        mock_server.sendmail.assert_called_once()
        mock_server.quit.assert_called_once()

    @patch("log_inspector.notifier.email_channel.smtplib.SMTP")
    def test_send_without_tls(self, mock_smtp_class):
        mock_server = MagicMock()
        mock_smtp_class.return_value = mock_server

        config = EmailNotifyConfig(
            enabled=True,
            smtp_host="smtp.test.com",
            smtp_port=25,
            use_tls=False,
            from_addr="from@test.com",
            to_addrs=["to@test.com"],
        )
        channel = EmailChannel(config)
        event = NotifyEvent(rule_name="test", level="error", message="Test")

        channel.send(event)
        mock_server.starttls.assert_not_called()


class TestWebhookChannel:
    @patch("log_inspector.notifier.webhook_channel.requests.request")
    def test_send_success(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_request.return_value = mock_response

        config = WebhookNotifyConfig(enabled=True, url="http://hook.test/api")
        channel = WebhookChannel(config)
        event = NotifyEvent(rule_name="test", level="error", message="Webhook test")

        result = channel.send(event)
        assert result is True
        mock_request.assert_called_once()
        call_kwargs = mock_request.call_args
        assert call_kwargs.kwargs["url"] == "http://hook.test/api"

    @patch("log_inspector.notifier.webhook_channel.requests.request")
    def test_send_failure(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_request.return_value = mock_response

        config = WebhookNotifyConfig(enabled=True, url="http://hook.test/api")
        channel = WebhookChannel(config)
        event = NotifyEvent(rule_name="test", level="error", message="Fail")

        result = channel.send(event)
        assert result is False


class TestDingTalkChannel:
    @patch("log_inspector.notifier.dingtalk_channel.requests.post")
    def test_send_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"errcode": 0}
        mock_post.return_value = mock_response

        config = DingTalkNotifyConfig(enabled=True, webhook_url="http://dingtalk.test/robot")
        channel = DingTalkChannel(config)
        event = NotifyEvent(rule_name="test", level="error", message="DingTalk test")

        result = channel.send(event)
        assert result is True


class TestNotificationDispatcher:
    def test_disabled_does_not_send(self):
        config = NotificationConfig(enabled=False)
        dispatcher = NotificationDispatcher(config)
        event = NotifyEvent(rule_name="test", level="error", message="Test")
        result = dispatcher.dispatch(event)
        assert result == []

    def test_level_filtering(self, notification_config):
        notification_config.min_level = "error"
        dispatcher = NotificationDispatcher(notification_config)
        event = NotifyEvent(rule_name="test", level="warning", message="Warning only")
        assert dispatcher.should_notify(event) is False

    def test_level_passes(self, notification_config):
        notification_config.min_level = "warning"
        dispatcher = NotificationDispatcher(notification_config)
        event = NotifyEvent(rule_name="test", level="error", message="Error")
        assert dispatcher.should_notify(event) is True

    def test_cooldown_dedup(self, notification_config):
        notification_config.cooldown_seconds = 10
        dispatcher = NotificationDispatcher(notification_config)
        event = NotifyEvent(rule_name="same_rule", level="error", message="Same message")

        # Simulate first send was done
        dedup_key = dispatcher._dedup_key(event)
        dispatcher._cooldown_map[dedup_key] = time.time()

        assert dispatcher.should_notify(event) is False

    def test_rule_notify_disabled(self, notification_config):
        dispatcher = NotificationDispatcher(notification_config)
        event = NotifyEvent(rule_name="test", level="error", message="Test")
        rule = RuleConfig(name="test", type="regex", pattern=".*", notify=False)
        assert dispatcher.should_notify(event, rule) is False

    @patch("log_inspector.notifier.email_channel.smtplib.SMTP")
    @patch("log_inspector.notifier.webhook_channel.requests.request")
    def test_dispatch_sends_to_channels(self, mock_request, mock_smtp_class):
        mock_server = MagicMock()
        mock_smtp_class.return_value = mock_server
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_request.return_value = mock_response

        config = NotificationConfig(
            enabled=True,
            min_level="error",
            cooldown_seconds=0,
            channels=["email", "webhook"],
            email=EmailNotifyConfig(
                enabled=True, smtp_host="localhost", smtp_port=25,
                from_addr="a@b.com", to_addrs=["c@d.com"], use_tls=False,
            ),
            webhook=WebhookNotifyConfig(enabled=True, url="http://hook.test"),
        )
        dispatcher = NotificationDispatcher(config)
        event = NotifyEvent(rule_name="test", level="error", message="Multi channel")

        sent = dispatcher.dispatch(event)
        assert "email" in sent
        assert "webhook" in sent
