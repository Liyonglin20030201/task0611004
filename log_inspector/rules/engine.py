"""规则引擎：加载、冲突检测、匹配"""

from __future__ import annotations

import re
from fnmatch import fnmatch
from itertools import combinations

from rich.console import Console

from log_inspector.config import RuleConfig
from log_inspector.parsers.base import LogEntry

console = Console(stderr=True)


class RuleConflict:
    def __init__(self, rule_a: RuleConfig, rule_b: RuleConfig, reason: str):
        self.rule_a = rule_a
        self.rule_b = rule_b
        self.reason = reason

    def __str__(self) -> str:
        return (
            f"冲突: [{self.rule_a.name}] vs [{self.rule_b.name}] — {self.reason}\n"
            f"  → 生效规则: {self.rule_a.name if self.rule_a.priority >= self.rule_b.priority else self.rule_b.name}"
            f" (优先级更高)"
        )


class CompiledRule:
    def __init__(self, config: RuleConfig):
        self.config = config
        self._regex: re.Pattern | None = None
        if config.type == "regex" and config.pattern:
            self._regex = re.compile(config.pattern, re.IGNORECASE)

    def matches(self, entry: LogEntry) -> bool:
        if not self.config.enabled:
            return False

        if self.config.type == "regex":
            if self._regex is None:
                return False
            return bool(self._regex.search(entry.message) or self._regex.search(entry.raw_line))

        elif self.config.type == "threshold":
            response_time = entry.metadata.get("response_time_ms")
            if response_time is None:
                return False
            return response_time >= (self.config.threshold or 0)

        elif self.config.type == "keyword":
            keywords = [k.strip() for k in self.config.pattern.split(",")]
            text = f"{entry.message} {entry.raw_line}".lower()
            return any(kw.lower() in text for kw in keywords)

        return False


class RuleEngine:
    def __init__(self, rules: list[RuleConfig]):
        sorted_rules = sorted(rules, key=lambda r: r.priority, reverse=True)
        self.rules = sorted_rules
        self.compiled: list[CompiledRule] = [CompiledRule(r) for r in sorted_rules]
        self.conflicts: list[RuleConflict] = []
        self._detect_conflicts()

    def _detect_conflicts(self):
        """检测同 scope 下互斥规则"""
        enabled_rules = [r for r in self.rules if r.enabled]
        for rule_a, rule_b in combinations(enabled_rules, 2):
            if not self._scopes_overlap(rule_a.scope, rule_b.scope):
                continue

            # 同一模式但动作矛盾
            if rule_a.pattern == rule_b.pattern and rule_a.action != rule_b.action:
                self.conflicts.append(RuleConflict(
                    rule_a, rule_b,
                    f"相同模式 '{rule_a.pattern}' 但动作不同 ({rule_a.action} vs {rule_b.action})"
                ))

            # 同类规则覆盖范围重叠
            if (rule_a.type == rule_b.type == "threshold"
                    and rule_a.threshold == rule_b.threshold
                    and rule_a.level != rule_b.level):
                self.conflicts.append(RuleConflict(
                    rule_a, rule_b,
                    f"相同阈值 {rule_a.threshold}ms 但级别不同 ({rule_a.level} vs {rule_b.level})"
                ))

    def _scopes_overlap(self, scope_a: str, scope_b: str) -> bool:
        if scope_a == "*" or scope_b == "*":
            return True
        return fnmatch(scope_a, scope_b) or fnmatch(scope_b, scope_a)

    def match(self, entry: LogEntry, rule_names: list[str] | None = None) -> list[RuleConfig]:
        """对一条日志记录执行所有规则匹配，返回匹配到的规则列表"""
        matched = []
        for compiled in self.compiled:
            if rule_names and compiled.config.name not in rule_names:
                continue
            if compiled.matches(entry):
                if compiled.config.action == "ignore":
                    return []
                matched.append(compiled.config)
        return matched

    def print_conflicts(self):
        if not self.conflicts:
            console.print("[green]未检测到规则冲突[/green]")
            return
        console.print(f"[yellow]检测到 {len(self.conflicts)} 个规则冲突:[/yellow]\n")
        for conflict in self.conflicts:
            console.print(f"  {conflict}\n")
