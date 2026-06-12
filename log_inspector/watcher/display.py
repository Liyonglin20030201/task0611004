"""实时监控的 Rich 显示输出"""

from __future__ import annotations

from rich.console import Console
from rich.text import Text

from log_inspector.config import RuleConfig
from log_inspector.parsers.base import LogEntry

console = Console()

LEVEL_COLORS = {
    "error": "red",
    "critical": "red bold",
    "warning": "yellow",
    "info": "green",
}


def format_match(entry: LogEntry, rules: list[RuleConfig], fmt: str = "rich") -> str | None:
    """格式化匹配结果用于实时输出"""
    if fmt == "json":
        import json
        return json.dumps({
            "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
            "line_number": entry.line_number,
            "rules": [r.name for r in rules],
            "level": rules[0].level if rules else "info",
            "message": entry.message,
        }, ensure_ascii=False)

    if fmt == "plain":
        rule_names = ", ".join(r.name for r in rules)
        ts = entry.timestamp.strftime("%H:%M:%S") if entry.timestamp else "--:--:--"
        level = rules[0].level if rules else "info"
        return f"[{ts}] [{level.upper()}] ({rule_names}) {entry.message[:200]}"

    return None


def print_match_rich(entry: LogEntry, rules: list[RuleConfig]):
    """使用 Rich 彩色输出匹配结果"""
    level = rules[0].level if rules else "info"
    color = LEVEL_COLORS.get(level, "white")
    rule_names = ", ".join(r.name for r in rules)
    ts = entry.timestamp.strftime("%H:%M:%S") if entry.timestamp else "--:--:--"

    console.print(
        f"[dim]{ts}[/dim] [{color}]{level.upper():8s}[/{color}] "
        f"[cyan]({rule_names})[/cyan] {entry.message[:200]}"
    )
