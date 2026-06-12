"""远程日志源解析器：将远程源解析为本地可用的文件或流"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Generator

from rich.console import Console

from log_inspector.config import RemoteLogSource
from log_inspector.remote.base import BaseTransport
from log_inspector.remote.ssh_transport import SSHTransport
from log_inspector.remote.s3_transport import S3Transport

console = Console(stderr=True)


class RemoteSourceResolver:
    """解析远程日志源，提供本地文件路径或行流"""

    def get_transport(self, source: RemoteLogSource) -> BaseTransport:
        if source.type == "ssh":
            if source.ssh is None:
                raise ValueError(f"远程源 '{source.name}' 类型为 ssh 但缺少 ssh 配置")
            return SSHTransport(source.ssh)
        elif source.type == "s3":
            if source.s3 is None:
                raise ValueError(f"远程源 '{source.name}' 类型为 s3 但缺少 s3 配置")
            return S3Transport(source.s3)
        else:
            raise ValueError(f"不支持的远程源类型: {source.type}")

    def fetch_to_local(self, source: RemoteLogSource) -> Path:
        """下载远程文件到本地临时目录，返回本地路径"""
        transport = self.get_transport(source)
        transport.connect()
        try:
            if source.download_dir:
                local_dir = Path(source.download_dir)
            else:
                local_dir = Path(tempfile.mkdtemp(prefix="log_inspector_"))
            filename = Path(source.remote_path).name
            local_path = local_dir / filename
            console.print(f"[blue]下载远程日志: {source.name} → {local_path}[/blue]")
            return transport.fetch(source.remote_path, local_path)
        finally:
            transport.disconnect()

    def fetch_stream(self, source: RemoteLogSource) -> Generator[str, None, None]:
        """流式获取远程文件内容"""
        transport = self.get_transport(source)
        transport.connect()
        try:
            yield from transport.fetch_stream(source.remote_path)
        finally:
            transport.disconnect()

    def test_connection(self, source: RemoteLogSource) -> bool:
        """测试远程源连接"""
        transport = self.get_transport(source)
        return transport.test_connection()

    def list_remote_files(self, source: RemoteLogSource, pattern: str = "*") -> list[str]:
        """列出远程文件"""
        transport = self.get_transport(source)
        transport.connect()
        try:
            return transport.list_files(pattern)
        finally:
            transport.disconnect()
