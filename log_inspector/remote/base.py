"""远程传输基类"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Generator


class BaseTransport(ABC):
    """远程日志传输抽象基类"""

    name: str = "base"

    @abstractmethod
    def connect(self):
        """建立连接"""
        ...

    @abstractmethod
    def disconnect(self):
        """断开连接"""
        ...

    @abstractmethod
    def fetch(self, remote_path: str, local_path: Path) -> Path:
        """下载远程文件到本地路径，返回本地路径"""
        ...

    @abstractmethod
    def fetch_stream(self, remote_path: str) -> Generator[str, None, None]:
        """流式读取远程文件，yield 每一行"""
        ...

    @abstractmethod
    def list_files(self, pattern: str = "*") -> list[str]:
        """列出远程文件"""
        ...

    def test_connection(self) -> bool:
        """测试连接是否正常"""
        try:
            self.connect()
            self.disconnect()
            return True
        except Exception:
            return False
