"""SSH 密钥管理与证书有效期校验"""

from __future__ import annotations

import os
import stat
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

console = Console(stderr=True)


def validate_ssh_key(key_path: str) -> tuple[bool, str]:
    """校验 SSH 密钥文件的有效性和权限"""
    path = Path(key_path)

    if not path.exists():
        return False, f"密钥文件不存在: {key_path}"

    if not path.is_file():
        return False, f"路径不是文件: {key_path}"

    if path.stat().st_size == 0:
        return False, f"密钥文件为空: {key_path}"

    if os.name != "nt":
        mode = path.stat().st_mode
        if mode & (stat.S_IRGRP | stat.S_IROTH):
            return False, f"密钥文件权限过宽: {oct(mode)}，建议 chmod 600"

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        first_line = f.readline().strip()
    if "PRIVATE KEY" not in first_line and "BEGIN" not in first_line:
        return False, f"文件不像是有效的 SSH 私钥: {key_path}"

    return True, "密钥文件校验通过"


def validate_cert_expiry(cert_path: str) -> tuple[bool, str]:
    """校验证书/密钥文件关联的 X.509 证书有效期。

    返回 (is_expired, message)。如果文件不是 X.509 证书则跳过校验。
    """
    path = Path(cert_path)
    if not path.exists():
        return False, "文件不存在，跳过有效期校验"

    content = path.read_text(encoding="utf-8", errors="replace")
    if "BEGIN CERTIFICATE" not in content:
        return False, "非 X.509 证书文件，跳过有效期校验"

    try:
        from cryptography import x509
        from cryptography.hazmat.primitives.serialization import Encoding

        cert_pem = _extract_cert_pem(content)
        cert = x509.load_pem_x509_certificate(cert_pem.encode())
        now = datetime.now(timezone.utc)

        if cert.not_valid_after_utc < now:
            return True, (
                f"证书已过期: 有效期至 {cert.not_valid_after_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}"
            )

        days_remaining = (cert.not_valid_after_utc - now).days
        if days_remaining < 30:
            console.print(
                f"[yellow]证书即将过期: 剩余 {days_remaining} 天 "
                f"(到期: {cert.not_valid_after_utc.strftime('%Y-%m-%d')})[/yellow]"
            )

        return False, f"证书有效，剩余 {days_remaining} 天"

    except ImportError:
        return _validate_cert_expiry_fallback(content)
    except Exception as e:
        return False, f"证书解析异常（跳过）: {e}"


def _extract_cert_pem(content: str) -> str:
    """从混合文件中提取第一个 PEM 证书块"""
    lines = content.splitlines()
    in_cert = False
    cert_lines = []
    for line in lines:
        if "BEGIN CERTIFICATE" in line:
            in_cert = True
            cert_lines.append(line)
        elif "END CERTIFICATE" in line:
            cert_lines.append(line)
            break
        elif in_cert:
            cert_lines.append(line)
    return "\n".join(cert_lines)


def _validate_cert_expiry_fallback(content: str) -> tuple[bool, str]:
    """无 cryptography 库时的降级校验（仅检测文件格式）"""
    if "BEGIN CERTIFICATE" in content and "END CERTIFICATE" in content:
        return False, "证书格式正确（需安装 cryptography 库进行有效期校验）"
    return False, "跳过有效期校验"


def get_default_key_paths() -> list[Path]:
    """获取默认 SSH 密钥路径"""
    ssh_dir = Path.home() / ".ssh"
    candidates = ["id_rsa", "id_ed25519", "id_ecdsa"]
    return [ssh_dir / name for name in candidates if (ssh_dir / name).exists()]
