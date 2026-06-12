"""pytest fixtures - 示例日志数据和公共配置"""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

import pytest

from log_inspector.config import (
    RuleConfig, Settings, SlowRequestThreshold, AuthConfig,
    NotificationConfig, EmailNotifyConfig, WebhookNotifyConfig,
    DingTalkNotifyConfig, WatchConfig, RemoteLogSource, SSHCredential,
    S3Credential, ProjectConfig, ProjectRegistry,
)
from log_inspector.db import Database


@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path


@pytest.fixture
def db(tmp_path) -> Database:
    return Database(tmp_path / "test.db")


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_path=str(tmp_path / "test.db"),
        export_dir=str(tmp_path / "exports"),
        plugin_dir=str(tmp_path / "plugins"),
        log_dir=str(tmp_path / "logs"),
        batch_size=100,
        slow_request=SlowRequestThreshold(warning_ms=1000.0, critical_ms=5000.0),
        auth=AuthConfig(enabled=False),
    )


@pytest.fixture
def notification_config() -> NotificationConfig:
    return NotificationConfig(
        enabled=True,
        min_level="error",
        cooldown_seconds=1,
        channels=["email", "webhook"],
        email=EmailNotifyConfig(
            enabled=True,
            smtp_host="localhost",
            smtp_port=587,
            from_addr="test@example.com",
            to_addrs=["admin@example.com"],
        ),
        webhook=WebhookNotifyConfig(
            enabled=True,
            url="http://localhost:8080/hook",
        ),
    )


@pytest.fixture
def settings_with_notification(tmp_path, notification_config) -> Settings:
    return Settings(
        database_path=str(tmp_path / "test.db"),
        export_dir=str(tmp_path / "exports"),
        plugin_dir=str(tmp_path / "plugins"),
        log_dir=str(tmp_path / "logs"),
        batch_size=100,
        slow_request=SlowRequestThreshold(warning_ms=1000.0, critical_ms=5000.0),
        auth=AuthConfig(enabled=False),
        notification=notification_config,
    )


@pytest.fixture
def growing_log_file(tmp_path):
    """创建一个在后台不断追加内容的日志文件"""
    log_file = tmp_path / "growing.log"
    log_file.write_text("", encoding="utf-8")

    stop_event = threading.Event()

    def _writer():
        lines = [
            '192.168.1.1 - - [10/Jun/2026:10:00:01 +0800] "GET /api/users HTTP/1.1" 200 100 "-" "ua" 0.05\n',
            '192.168.1.2 - - [10/Jun/2026:10:00:02 +0800] "GET /api/error HTTP/1.1" 500 50 "-" "ua" 0.10\n',
            '192.168.1.3 - - [10/Jun/2026:10:00:03 +0800] "GET /api/slow HTTP/1.1" 200 200 "-" "ua" 5.00\n',
        ]
        idx = 0
        while not stop_event.is_set():
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(lines[idx % len(lines)])
            idx += 1
            time.sleep(0.1)

    writer_thread = threading.Thread(target=_writer, daemon=True)
    writer_thread.start()

    yield log_file

    stop_event.set()
    writer_thread.join(timeout=2)


@pytest.fixture
def sample_nginx_log(tmp_path) -> Path:
    content = """192.168.1.1 - - [10/Jun/2026:10:00:01 +0800] "GET /api/users HTTP/1.1" 200 1234 "-" "Mozilla/5.0" 0.052
192.168.1.2 - - [10/Jun/2026:10:00:02 +0800] "POST /api/login HTTP/1.1" 200 567 "-" "curl/7.68" 0.120
192.168.1.3 - - [10/Jun/2026:10:00:03 +0800] "GET /api/orders HTTP/1.1" 500 89 "-" "Mozilla/5.0" 2.500
192.168.1.4 - - [10/Jun/2026:10:00:04 +0800] "GET /static/js/app.js HTTP/1.1" 304 0 "-" "Mozilla/5.0" 0.001
192.168.1.5 - - [10/Jun/2026:10:00:05 +0800] "GET /api/slow HTTP/1.1" 200 2048 "-" "Mozilla/5.0" 6.200
192.168.1.6 - - [10/Jun/2026:10:00:06 +0800] "GET /health HTTP/1.1" 200 2 "-" "kube-probe" 0.001
192.168.1.7 - - [10/Jun/2026:10:00:07 +0800] "DELETE /api/users/1 HTTP/1.1" 403 45 "-" "Mozilla/5.0" 0.015
192.168.1.8 - - [10/Jun/2026:10:00:08 +0800] "GET /api/timeout HTTP/1.1" 504 0 "-" "Mozilla/5.0" 30.000
"""
    log_file = tmp_path / "access.log"
    log_file.write_text(content, encoding="utf-8")
    return log_file


@pytest.fixture
def sample_node_log(tmp_path) -> Path:
    content = """{"level":"info","message":"Server started on port 3000","timestamp":"2026-06-10T10:00:00.000Z"}
{"level":"error","message":"Uncaught exception: Cannot read property 'id' of undefined","timestamp":"2026-06-10T10:00:01.000Z","stack":"TypeError: ..."}
{"level":"warn","message":"Deprecated API called: /v1/users","timestamp":"2026-06-10T10:00:02.000Z"}
{"level":"info","message":"Request completed","timestamp":"2026-06-10T10:00:03.000Z","method":"GET","path":"/api/data","statusCode":200,"responseTime":1500}
{"level":"error","message":"Database connection refused","timestamp":"2026-06-10T10:00:04.000Z","code":"ECONNREFUSED"}
{"level":"info","message":"Health check OK","timestamp":"2026-06-10T10:00:05.000Z"}
"""
    log_file = tmp_path / "node.log"
    log_file.write_text(content, encoding="utf-8")
    return log_file


@pytest.fixture
def sample_python_log(tmp_path) -> Path:
    content = """2026-06-10 10:00:00,123 - django.request - ERROR - Internal Server Error: /api/checkout
2026-06-10 10:00:01,456 - celery.worker - INFO - Task payment.process started
2026-06-10 10:00:02,789 - django.db - WARNING - Database connection pool exhausted
Traceback (most recent call last):
  File "/app/views.py", line 42, in checkout
    result = process_payment(order)
ValueError: Invalid payment amount
2026-06-10 10:00:05,000 - gunicorn.access - INFO - GET /api/products 200 took 50ms
2026-06-10 10:00:06,000 - gunicorn.access - WARNING - GET /api/search 200 took 3500ms
"""
    log_file = tmp_path / "django.log"
    log_file.write_text(content, encoding="utf-8")
    return log_file


@pytest.fixture
def sample_rules() -> list[RuleConfig]:
    return [
        RuleConfig(name="test_5xx", type="regex", pattern=r"\s5\d{2}\s", level="error", priority=10),
        RuleConfig(name="test_slow", type="threshold", threshold=1000.0, level="warning", priority=8),
        RuleConfig(name="test_keyword", type="keyword", pattern="error,exception", level="error", priority=9),
    ]
