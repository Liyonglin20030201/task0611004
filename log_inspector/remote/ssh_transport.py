"""SSH/SFTP 传输实现（强制加密通道）"""

from __future__ import annotations

import fnmatch
import io
import tempfile
from pathlib import Path, PurePosixPath
from typing import Generator

from log_inspector.config import SSHCredential
from log_inspector.remote.base import BaseTransport


class SSHTransport(BaseTransport):
    """通过 SSH/SFTP 协议获取远程日志（强制 TLS 加密）"""

    name = "ssh"

    def __init__(self, credential: SSHCredential):
        self.credential = credential
        self._client = None
        self._sftp = None

    def connect(self):
        try:
            import paramiko
        except ImportError:
            raise ImportError("请安装 paramiko: pip install log-inspector[remote]")

        if self.credential.key_file:
            from log_inspector.remote.key_manager import validate_ssh_key, validate_cert_expiry
            ok, msg = validate_ssh_key(self.credential.key_file)
            if not ok:
                raise ValueError(f"SSH 密钥校验失败: {msg}")
            expired, exp_msg = validate_cert_expiry(self.credential.key_file)
            if expired:
                raise ValueError(f"证书有效期校验失败: {exp_msg}")

        self._client = paramiko.SSHClient()

        if self.credential.host_key_verify:
            self._client.load_system_host_keys()
            self._client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            "hostname": self.credential.host,
            "port": self.credential.port,
            "username": self.credential.username,
        }

        if self.credential.key_file:
            key = paramiko.RSAKey.from_private_key_file(
                self.credential.key_file,
                password=self.credential.passphrase or None,
            )
            connect_kwargs["pkey"] = key
        elif self.credential.password:
            connect_kwargs["password"] = self.credential.password

        self._client.connect(**connect_kwargs)

        transport = self._client.get_transport()
        if self.credential.force_tls and transport:
            cipher = transport.remote_cipher
            if cipher and "none" in cipher.lower():
                self._client.close()
                raise ConnectionError("远程传输未使用加密通道，force_tls 要求加密连接")

        self._sftp = self._client.open_sftp()

    def disconnect(self):
        if self._sftp:
            self._sftp.close()
            self._sftp = None
        if self._client:
            self._client.close()
            self._client = None

    def fetch(self, remote_path: str, local_path: Path) -> Path:
        if self._sftp is None:
            self.connect()
        local_path.parent.mkdir(parents=True, exist_ok=True)
        self._sftp.get(remote_path, str(local_path))
        return local_path

    def fetch_stream(self, remote_path: str) -> Generator[str, None, None]:
        if self._sftp is None:
            self.connect()
        with self._sftp.open(remote_path, "r") as remote_file:
            for line in remote_file:
                if isinstance(line, bytes):
                    yield line.decode("utf-8", errors="replace").rstrip("\n\r")
                else:
                    yield line.rstrip("\n\r")

    def list_files(self, pattern: str = "*") -> list[str]:
        if self._sftp is None:
            self.connect()
        remote_dir = str(PurePosixPath(pattern).parent)
        file_pattern = PurePosixPath(pattern).name
        try:
            entries = self._sftp.listdir(remote_dir)
            matched = [
                f"{remote_dir}/{name}"
                for name in entries
                if fnmatch.fnmatch(name, file_pattern)
            ]
            return sorted(matched)
        except IOError:
            return []
