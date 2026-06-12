"""文件尾部跟踪器：类似 tail -f 的持续读取"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Generator


class FileTailer:
    """持续跟踪文件新增内容，支持文件轮转检测"""

    def __init__(self, path: Path, poll_interval_ms: int = 500, from_end: bool = True):
        self._path = path
        self._poll_interval = poll_interval_ms / 1000.0
        self._position = 0
        self._inode = None
        self._from_end = from_end

    def follow(self) -> Generator[str, None, None]:
        """持续 yield 新行，处理文件轮转"""
        if self._from_end:
            self._seek_to_end()
        else:
            self._position = 0
            self._update_inode()

        while True:
            if self._file_rotated():
                self._reopen()

            lines = self._read_new_lines()
            if lines:
                yield from lines
            else:
                time.sleep(self._poll_interval)

    def _seek_to_end(self):
        try:
            stat = self._path.stat()
            self._position = stat.st_size
            self._inode = self._get_inode()
        except OSError:
            self._position = 0
            self._inode = None

    def _update_inode(self):
        self._inode = self._get_inode()

    def _get_inode(self) -> int | None:
        try:
            stat = self._path.stat()
            if os.name == "nt":
                return int(stat.st_ctime_ns)
            return stat.st_ino
        except OSError:
            return None

    def _file_rotated(self) -> bool:
        """检测文件是否被轮转（inode 变化或文件缩小）"""
        try:
            stat = self._path.stat()
            current_inode = self._get_inode()
            if self._inode is not None and current_inode != self._inode:
                return True
            if stat.st_size < self._position:
                return True
        except OSError:
            pass
        return False

    def _reopen(self):
        self._position = 0
        self._inode = self._get_inode()

    def _read_new_lines(self) -> list[str]:
        lines = []
        try:
            with open(self._path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._position)
                buffer = f.read()
                if buffer:
                    self._position = f.tell()
                    for line in buffer.splitlines(True):
                        if line.endswith("\n"):
                            lines.append(line.rstrip("\n\r"))
                        else:
                            self._position -= len(line.encode("utf-8", errors="replace"))
        except OSError:
            pass
        return lines
