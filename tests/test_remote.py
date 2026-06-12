"""远程日志聚合测试"""

from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

import pytest

from log_inspector.config import (
    RemoteLogSource, SSHCredential, S3Credential, Settings,
    SlowRequestThreshold, AuthConfig,
)
from log_inspector.db import Database
from log_inspector.remote.base import BaseTransport
from log_inspector.remote.resolver import RemoteSourceResolver
from log_inspector.remote.key_manager import validate_ssh_key, get_default_key_paths


class TestRemoteSourceResolver:
    def test_get_transport_ssh(self):
        source = RemoteLogSource(
            name="test-ssh",
            type="ssh",
            ssh=SSHCredential(host="192.168.1.1", username="user"),
            remote_path="/var/log/app.log",
        )
        resolver = RemoteSourceResolver()
        transport = resolver.get_transport(source)
        assert transport.name == "ssh"

    def test_get_transport_s3(self):
        source = RemoteLogSource(
            name="test-s3",
            type="s3",
            s3=S3Credential(bucket="my-bucket", region="us-east-1"),
            remote_path="logs/app.log",
        )
        resolver = RemoteSourceResolver()
        transport = resolver.get_transport(source)
        assert transport.name == "s3"

    def test_get_transport_invalid_type(self):
        source = RemoteLogSource(name="bad", type="ftp", remote_path="/tmp/x")
        resolver = RemoteSourceResolver()
        with pytest.raises(ValueError, match="不支持的远程源类型"):
            resolver.get_transport(source)

    def test_get_transport_ssh_missing_config(self):
        source = RemoteLogSource(name="bad", type="ssh", remote_path="/tmp/x")
        resolver = RemoteSourceResolver()
        with pytest.raises(ValueError, match="缺少 ssh 配置"):
            resolver.get_transport(source)


class TestSSHTransport:
    @patch("paramiko.SSHClient")
    @patch("paramiko.RSAKey")
    def test_connect(self, mock_rsa, mock_ssh_client):
        from log_inspector.remote.ssh_transport import SSHTransport

        cred = SSHCredential(host="test.host", port=22, username="deploy", password="secret")
        transport = SSHTransport(cred)
        transport.connect()

        mock_ssh_client.assert_called_once()
        mock_ssh_client.return_value.connect.assert_called_once()

    @patch("paramiko.SSHClient")
    @patch("paramiko.RSAKey")
    def test_fetch(self, mock_rsa, mock_ssh_client, tmp_path):
        from log_inspector.remote.ssh_transport import SSHTransport

        mock_sftp = MagicMock()
        mock_ssh_client.return_value.open_sftp.return_value = mock_sftp

        cred = SSHCredential(host="test.host", username="deploy", password="secret")
        transport = SSHTransport(cred)
        transport.connect()

        local_path = tmp_path / "downloaded.log"
        result = transport.fetch("/var/log/app.log", local_path)
        assert result == local_path
        mock_sftp.get.assert_called_once_with("/var/log/app.log", str(local_path))

    @patch("paramiko.SSHClient")
    @patch("paramiko.RSAKey")
    def test_disconnect(self, mock_rsa, mock_ssh_client):
        from log_inspector.remote.ssh_transport import SSHTransport

        cred = SSHCredential(host="test.host", username="deploy", password="secret")
        transport = SSHTransport(cred)
        transport.connect()
        transport.disconnect()

        mock_ssh_client.return_value.close.assert_called_once()


class TestS3Transport:
    @patch("boto3.client")
    def test_connect(self, mock_boto3_client):
        from log_inspector.remote.s3_transport import S3Transport

        cred = S3Credential(bucket="my-logs", region="us-east-1",
                           access_key="AK", secret_key="SK")
        transport = S3Transport(cred)
        transport.connect()

        mock_boto3_client.assert_called_once_with(
            "s3", region_name="us-east-1",
            aws_access_key_id="AK", aws_secret_access_key="SK",
        )

    @patch("boto3.client")
    def test_fetch(self, mock_boto3_client, tmp_path):
        from log_inspector.remote.s3_transport import S3Transport

        cred = S3Credential(bucket="my-logs", region="us-east-1")
        transport = S3Transport(cred)
        transport.connect()

        local_path = tmp_path / "s3_download.log"
        transport.fetch("logs/app.log", local_path)

        mock_boto3_client.return_value.download_file.assert_called_once_with(
            "my-logs", "logs/app.log", str(local_path),
        )


class TestKeyManager:
    def test_validate_nonexistent_key(self, tmp_path):
        ok, msg = validate_ssh_key(str(tmp_path / "nonexistent"))
        assert ok is False
        assert "不存在" in msg

    def test_validate_empty_key(self, tmp_path):
        key_file = tmp_path / "empty_key"
        key_file.write_text("")
        ok, msg = validate_ssh_key(str(key_file))
        assert ok is False
        assert "为空" in msg

    def test_validate_invalid_key_content(self, tmp_path):
        key_file = tmp_path / "bad_key"
        key_file.write_text("this is not a key file\nrandom content\n")
        ok, msg = validate_ssh_key(str(key_file))
        assert ok is False
        assert "不像是有效" in msg

    def test_validate_valid_key(self, tmp_path):
        key_file = tmp_path / "good_key"
        key_file.write_text("-----BEGIN RSA PRIVATE KEY-----\nfake key content\n-----END RSA PRIVATE KEY-----\n")
        ok, msg = validate_ssh_key(str(key_file))
        assert ok is True


class TestScanRemote:
    @patch("paramiko.SSHClient")
    @patch("paramiko.RSAKey")
    def test_scan_remote_pipeline(self, mock_rsa, mock_ssh_client, tmp_path):
        mock_sftp = MagicMock()
        mock_ssh_client.return_value.open_sftp.return_value = mock_sftp

        log_content = (
            '1.1.1.1 - - [10/Jun/2026:10:00:01 +0800] "GET /api HTTP/1.1" 500 50 "-" "ua" 0.1\n'
            '1.1.1.1 - - [10/Jun/2026:10:00:02 +0800] "GET /ok HTTP/1.1" 200 50 "-" "ua" 0.1\n'
        )

        def fake_get(remote_path, local_path):
            Path(local_path).write_text(log_content, encoding="utf-8")

        mock_sftp.get.side_effect = fake_get

        source = RemoteLogSource(
            name="test-remote",
            type="ssh",
            ssh=SSHCredential(host="test.host", username="user", password="pass"),
            remote_path="/var/log/app.log",
            parser="nginx",
            download_dir=str(tmp_path),
        )

        from log_inspector.scanner import Scanner
        db = Database(tmp_path / "test.db")
        settings = Settings(
            database_path=str(tmp_path / "test.db"),
            batch_size=100,
            slow_request=SlowRequestThreshold(warning_ms=1000.0, critical_ms=5000.0),
            auth=AuthConfig(enabled=False),
        )

        scanner = Scanner(db, settings)
        scan_id = scanner.scan_remote(source)

        scan = db.get_scan(scan_id)
        assert scan["status"] == "completed"
        assert scan["total_lines"] == 2
