"""运行日志配置"""

from __future__ import annotations

import logging
from pathlib import Path


def setup_logging(log_dir: str = "logs", level: str = "INFO") -> logging.Logger:
    """配置工具自身的运行日志"""
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("log_inspector")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not logger.handlers:
        # File handler
        fh = logging.FileHandler(
            log_path / "log_inspector.log",
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ))
        logger.addHandler(fh)

        # Console handler (only warnings+)
        ch = logging.StreamHandler()
        ch.setLevel(logging.WARNING)
        ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(ch)

    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger("log_inspector")
