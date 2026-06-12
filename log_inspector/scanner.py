"""核心扫描引擎：流式读取、编码检测、规则匹配、批量存储"""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

import chardet
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from log_inspector.config import Settings, RuleConfig
from log_inspector.db import Database
from log_inspector.notifier import NotificationDispatcher, NotifyEvent
from log_inspector.parsers.base import BaseParser, LogEntry
from log_inspector.parsers.nginx import NginxParser
from log_inspector.parsers.node import NodeParser
from log_inspector.parsers.python_log import PythonLogParser
from log_inspector.rules.engine import RuleEngine

console = Console(stderr=True)

BUILTIN_PARSERS: dict[str, type[BaseParser]] = {
    "nginx": NginxParser,
    "node": NodeParser,
    "python": PythonLogParser,
}


def detect_encoding(file_path: Path) -> str:
    """对文件前 10KB 采样检测编码"""
    with open(file_path, "rb") as f:
        raw = f.read(10240)
    result = chardet.detect(raw)
    return result.get("encoding") or "utf-8"


def open_log_file(file_path: Path, encoding: str = "utf-8") -> Generator[str, None, None]:
    """流式读取日志文件，支持 gzip 和编码回退"""
    opener = gzip.open if file_path.suffix == ".gz" else open

    try:
        with opener(file_path, "rt", encoding=encoding, errors="replace") as f:
            yield from f
    except UnicodeDecodeError:
        detected = detect_encoding(file_path)
        console.print(f"[yellow]编码回退: {encoding} → {detected}[/yellow]")
        with opener(file_path, "rt", encoding=detected, errors="replace") as f:
            yield from f


def auto_detect_parser(file_path: Path, custom_parsers: list[BaseParser] | None = None) -> BaseParser:
    """根据文件内容自动选择解析器"""
    sample_lines = []
    try:
        for i, line in enumerate(open_log_file(file_path)):
            sample_lines.append(line)
            if i >= 20:
                break
    except Exception:
        pass

    all_parsers: list[BaseParser] = [p() for p in BUILTIN_PARSERS.values()]
    if custom_parsers:
        all_parsers.extend(custom_parsers)

    for parser in all_parsers:
        if parser.can_parse(sample_lines):
            return parser

    # Default to nginx if path hints
    name_lower = file_path.name.lower()
    if "nginx" in name_lower or "access" in name_lower:
        return NginxParser()
    if "node" in name_lower or "pm2" in name_lower:
        return NodeParser()

    return PythonLogParser()


class Scanner:
    def __init__(self, db: Database, settings: Settings,
                 notifier: NotificationDispatcher | None = None):
        self.db = db
        self.settings = settings
        self.batch_size = settings.batch_size
        self._notifier = notifier
        if self._notifier is None and settings.notification.enabled:
            self._notifier = NotificationDispatcher(settings.notification)

    def scan(
        self,
        log_path: Path,
        parser_type: str = "auto",
        rules: list[RuleConfig] | None = None,
        rule_names: list[str] | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        custom_parsers: list[BaseParser] | None = None,
    ) -> int:
        """执行扫描，返回 scan_id"""
        if not log_path.exists():
            console.print(f"[red]文件不存在: {log_path}[/red]")
            raise FileNotFoundError(f"{log_path}")

        # Select parser
        if parser_type == "auto":
            parser = auto_detect_parser(log_path, custom_parsers)
        elif parser_type in BUILTIN_PARSERS:
            parser = BUILTIN_PARSERS[parser_type]()
        else:
            parser = auto_detect_parser(log_path, custom_parsers)

        # Create scan record
        scan_id = self.db.create_scan(
            log_path=str(log_path),
            parser_type=parser.name,
            start_time=start_time.isoformat() if start_time else None,
            end_time=end_time.isoformat() if end_time else None,
        )

        # Setup rule engine
        if rules is None:
            from log_inspector.rules.builtin import BUILTIN_RULES
            rules = BUILTIN_RULES
        engine = RuleEngine(rules)

        if engine.conflicts:
            engine.print_conflicts()

        # Scan
        try:
            total_lines, matched_lines = self._process_file(
                log_path, parser, engine, scan_id, rule_names, start_time, end_time
            )
            self.db.update_scan(scan_id, "completed", total_lines, matched_lines)
            console.print(
                f"[green]扫描完成:[/green] {total_lines} 行已处理, "
                f"{matched_lines} 条匹配 (scan_id={scan_id})"
            )
        except Exception as e:
            self.db.update_scan(scan_id, "failed", 0, 0)
            console.print(f"[red]扫描失败: {e}[/red]")
            raise

        return scan_id

    def _process_file(
        self,
        log_path: Path,
        parser: BaseParser,
        engine: RuleEngine,
        scan_id: int,
        rule_names: list[str] | None,
        start_time: datetime | None,
        end_time: datetime | None,
    ) -> tuple[int, int]:
        total_lines = 0
        matched_lines = 0
        findings_batch: list[dict] = []
        slow_batch: list[dict] = []

        file_size = log_path.stat().st_size
        use_progress = file_size > 1024 * 1024  # > 1MB show progress

        encoding = self.settings.log_sources[0].encoding if self.settings.log_sources else "utf-8"

        # 归一化时间比较：统一去掉时区信息做本地时间对比
        def _normalize_for_compare(ts: datetime) -> datetime:
            if ts.tzinfo is not None:
                return ts.replace(tzinfo=None)
            return ts

        norm_start = _normalize_for_compare(start_time) if start_time else None
        norm_end = _normalize_for_compare(end_time) if end_time else None

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
            disable=not use_progress,
        ) as progress:
            task = progress.add_task(f"扫描 {log_path.name}", total=file_size)
            bytes_read = 0

            for line in open_log_file(log_path, encoding):
                total_lines += 1
                bytes_read += len(line.encode("utf-8", errors="replace"))
                progress.update(task, completed=min(bytes_read, file_size))

                entry = parser.parse_line(line, total_lines)
                if entry is None:
                    continue

                # Time filter
                if entry.timestamp:
                    entry_local = _normalize_for_compare(entry.timestamp)
                    if norm_start and entry_local < norm_start:
                        continue
                    if norm_end and entry_local > norm_end:
                        continue

                # Rule matching
                matched_rules = engine.match(entry, rule_names)
                if matched_rules:
                    matched_lines += 1
                    for rule in matched_rules:
                        findings_batch.append({
                            "scan_id": scan_id,
                            "line_number": entry.line_number,
                            "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                            "level": rule.level,
                            "rule_name": rule.name,
                            "category": self._categorize(rule),
                            "message": entry.message,
                            "raw_line": entry.raw_line[:1000],
                            "metadata": json.dumps(entry.metadata, ensure_ascii=False),
                        })

                        if self._notifier and rule.notify:
                            event = NotifyEvent(
                                rule_name=rule.name,
                                level=rule.level,
                                message=entry.message,
                                scan_id=scan_id,
                                timestamp=entry.timestamp,
                                metadata=entry.metadata,
                            )
                            sent = self._notifier.dispatch(event, rule)
                            if sent:
                                for ch in sent:
                                    self.db.insert_notification(scan_id, rule.name, ch)

                # Slow request detection
                rt = entry.metadata.get("response_time_ms")
                if rt is not None and rt >= self.settings.slow_request.warning_ms:
                    slow_batch.append({
                        "scan_id": scan_id,
                        "path": entry.metadata.get("path", ""),
                        "method": entry.metadata.get("method", ""),
                        "response_time_ms": rt,
                        "status_code": entry.metadata.get("status_code"),
                        "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                    })

                # Batch insert
                if len(findings_batch) >= self.batch_size:
                    self.db.insert_findings_batch(findings_batch)
                    findings_batch.clear()
                if len(slow_batch) >= self.batch_size:
                    self.db.insert_slow_requests_batch(slow_batch)
                    slow_batch.clear()

        # Flush remaining
        if findings_batch:
            self.db.insert_findings_batch(findings_batch)
        if slow_batch:
            self.db.insert_slow_requests_batch(slow_batch)

        return total_lines, matched_lines

    def _categorize(self, rule: RuleConfig) -> str:
        if rule.type == "threshold":
            return "slow_request"
        if rule.level == "error":
            return "error"
        return "anomaly"

    def match_entry(self, entry: LogEntry, engine: RuleEngine,
                    rule_names: list[str] | None = None) -> list[RuleConfig]:
        """对单条日志执行规则匹配，供 watch 模式复用"""
        return engine.match(entry, rule_names)

    def scan_remote(
        self,
        source,
        rules: list[RuleConfig] | None = None,
        rule_names: list[str] | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> int:
        """扫描远程日志源"""
        from log_inspector.remote import RemoteSourceResolver

        resolver = RemoteSourceResolver()
        local_path = resolver.fetch_to_local(source)
        return self.scan(
            log_path=local_path,
            parser_type=source.parser,
            rules=rules,
            rule_names=rule_names,
            start_time=start_time,
            end_time=end_time,
        )

    def scan_stream(
        self,
        line_generator: Generator[str, None, None],
        parser_type: str = "auto",
        source_name: str = "",
        rules: list[RuleConfig] | None = None,
        rule_names: list[str] | None = None,
    ) -> int:
        """流式扫描（不落地文件），返回 scan_id"""
        if parser_type in BUILTIN_PARSERS:
            parser = BUILTIN_PARSERS[parser_type]()
        else:
            parser = PythonLogParser()

        scan_id = self.db.create_scan(
            log_path=f"stream://{source_name}",
            parser_type=parser.name,
            source_type="remote",
            source_name=source_name,
        )

        if rules is None:
            from log_inspector.rules.builtin import BUILTIN_RULES
            rules = BUILTIN_RULES
        engine = RuleEngine(rules)

        total_lines = 0
        matched_lines = 0
        findings_batch: list[dict] = []

        try:
            for line in line_generator:
                total_lines += 1
                entry = parser.parse_line(line, total_lines)
                if entry is None:
                    continue

                matched_rules = engine.match(entry, rule_names)
                if matched_rules:
                    matched_lines += 1
                    for rule in matched_rules:
                        findings_batch.append({
                            "scan_id": scan_id,
                            "line_number": entry.line_number,
                            "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                            "level": rule.level,
                            "rule_name": rule.name,
                            "category": self._categorize(rule),
                            "message": entry.message,
                            "raw_line": entry.raw_line[:1000],
                            "metadata": json.dumps(entry.metadata, ensure_ascii=False),
                        })

                if len(findings_batch) >= self.batch_size:
                    self.db.insert_findings_batch(findings_batch)
                    findings_batch.clear()

            if findings_batch:
                self.db.insert_findings_batch(findings_batch)

            self.db.update_scan(scan_id, "completed", total_lines, matched_lines)
            console.print(
                f"[green]流式扫描完成:[/green] {total_lines} 行, "
                f"{matched_lines} 条匹配 (scan_id={scan_id})"
            )
        except Exception as e:
            self.db.update_scan(scan_id, "failed", total_lines, matched_lines)
            console.print(f"[red]流式扫描失败: {e}[/red]")
            raise

        return scan_id
