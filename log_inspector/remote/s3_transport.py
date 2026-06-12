"""S3 兼容存储传输实现（强制 TLS）"""

from __future__ import annotations

import fnmatch
import tempfile
from pathlib import Path
from typing import Generator

from log_inspector.config import S3Credential
from log_inspector.remote.base import BaseTransport


class S3Transport(BaseTransport):
    """通过 S3 兼容协议获取远程日志（强制 SSL/TLS）"""

    name = "s3"

    def __init__(self, credential: S3Credential):
        self.credential = credential
        self._client = None

    def connect(self):
        try:
            import boto3
        except ImportError:
            raise ImportError("请安装 boto3: pip install log-inspector[remote]")

        if not self.credential.use_ssl:
            raise ConnectionError(
                "S3 传输必须启用 SSL/TLS 加密 (use_ssl: true)。"
                "禁止明文传输日志数据"
            )

        kwargs = {"use_ssl": True}
        if self.credential.endpoint_url:
            kwargs["endpoint_url"] = self.credential.endpoint_url
        if self.credential.region:
            kwargs["region_name"] = self.credential.region
        if self.credential.access_key:
            kwargs["aws_access_key_id"] = self.credential.access_key
            kwargs["aws_secret_access_key"] = self.credential.secret_key
        if self.credential.ca_bundle:
            kwargs["verify"] = self.credential.ca_bundle
        elif self.credential.verify_ssl:
            kwargs["verify"] = True
        else:
            kwargs["verify"] = True

        self._client = boto3.client("s3", **kwargs)

    def disconnect(self):
        self._client = None

    def fetch(self, remote_path: str, local_path: Path) -> Path:
        if self._client is None:
            self.connect()
        local_path.parent.mkdir(parents=True, exist_ok=True)
        self._client.download_file(
            self.credential.bucket, remote_path, str(local_path)
        )
        return local_path

    def fetch_stream(self, remote_path: str) -> Generator[str, None, None]:
        if self._client is None:
            self.connect()
        response = self._client.get_object(
            Bucket=self.credential.bucket, Key=remote_path
        )
        body = response["Body"]
        try:
            for line in body.iter_lines():
                if isinstance(line, bytes):
                    yield line.decode("utf-8", errors="replace")
                else:
                    yield line
        finally:
            body.close()

    def list_files(self, pattern: str = "*") -> list[str]:
        if self._client is None:
            self.connect()
        prefix = self.credential.prefix
        paginator = self._client.get_paginator("list_objects_v2")
        matched = []
        for page in paginator.paginate(Bucket=self.credential.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if fnmatch.fnmatch(key.split("/")[-1], pattern):
                    matched.append(key)
        return sorted(matched)
