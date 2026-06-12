"""Typer CLI 入口 - 注册所有命令"""

from __future__ import annotations

import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from log_inspector.config import (
    DEFAULT_CONFIG_DIR,
    load_rules,
    load_settings,
    load_tasks,
    load_projects,
    load_yaml,
    validate_config,
    try_load_yaml,
    try_validate_config,
    RulesFile,
    Settings,
    TasksFile,
    ProjectRegistry,
)
from log_inspector.db import Database
from log_inspector.logger import setup_logging

console = Console()
app = typer.Typer(name="log-inspector", help="本地服务器日志巡检工具")
rules_app = typer.Typer(help="规则管理")
report_app = typer.Typer(help="报告查询")
schedule_app = typer.Typer(help="定时任务管理")
config_app = typer.Typer(help="配置管理")
plugin_app = typer.Typer(help="插件管理")
notify_app = typer.Typer(help="通知管理")
remote_app = typer.Typer(help="远程日志源管理")
project_app = typer.Typer(help="项目管理")

app.add_typer(rules_app, name="rules")
app.add_typer(report_app, name="report")
app.add_typer(schedule_app, name="schedule")
app.add_typer(config_app, name="config")
app.add_typer(plugin_app, name="plugin")
app.add_typer(notify_app, name="notify")
app.add_typer(remote_app, name="remote")
app.add_typer(project_app, name="project")


# ─── Global options ─────────────────────────────────────────────────────────

_current_project: str | None = None


@app.callback()
def main_callback(
    project: Optional[str] = typer.Option(None, "--project", "-P", help="指定项目 ID"),
):
    """全局选项"""
    global _current_project
    if project:
        _current_project = project
        from log_inspector.projects.context import set_current_project
        set_current_project(project)


def _get_db(settings: Settings | None = None) -> Database:
    if settings is None:
        settings = load_settings()
    return Database(settings.database_path)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    console.print(f"[red]无法解析时间: {value}[/red]")
    raise typer.Exit(1)


# ─── scan ────────────────────────────────────────────────────────────────────

@app.command()
def scan(
    log_path: str = typer.Argument(..., help="日志文件或目录路径"),
    parser: str = typer.Option("auto", "--parser", "-p", help="解析器类型: auto/nginx/node/python"),
    start: Optional[str] = typer.Option(None, "--start", "-s", help="开始时间 (YYYY-MM-DD HH:MM:SS)"),
    end: Optional[str] = typer.Option(None, "--end", "-e", help="结束时间 (YYYY-MM-DD HH:MM:SS)"),
    rule: Optional[str] = typer.Option(None, "--rule", "-r", help="指定规则名称（逗号分隔）"),
    config_dir: Optional[str] = typer.Option(None, "--config-dir", help="配置目录路径"),
):
    """扫描日志文件，检测异常"""
    setup_logging()
    cfg_dir = Path(config_dir) if config_dir else None
    settings = load_settings(cfg_dir)

    from log_inspector.auth import require_permission
    require_permission(settings.auth)

    from log_inspector.plugins import PluginLoader
    from log_inspector.scanner import Scanner

    db = _get_db(settings)
    rules = load_rules(cfg_dir)
    plugin_loader = PluginLoader(settings.plugin_dir)
    custom_parsers = plugin_loader.load_all()

    start_time = _parse_time(start)
    end_time = _parse_time(end)
    rule_names = [r.strip() for r in rule.split(",")] if rule else None

    target = Path(log_path)
    scanner = Scanner(db, settings)

    if target.is_dir():
        log_files = list(target.glob("**/*.log")) + list(target.glob("**/*.log.gz"))
        if not log_files:
            console.print(f"[yellow]目录中未找到日志文件: {target}[/yellow]")
            raise typer.Exit(1)
        console.print(f"[blue]发现 {len(log_files)} 个日志文件[/blue]")
        for f in log_files:
            scanner.scan(
                log_path=f,
                parser_type=parser,
                rules=rules,
                rule_names=rule_names,
                start_time=start_time,
                end_time=end_time,
                custom_parsers=custom_parsers,
            )
    else:
        scanner.scan(
            log_path=target,
            parser_type=parser,
            rules=rules,
            rule_names=rule_names,
            start_time=start_time,
            end_time=end_time,
            custom_parsers=custom_parsers,
        )


# ─── watch ──────────────────────────────────────────────────────────────────

@app.command()
def watch(
    log_path: str = typer.Argument(..., help="日志文件路径"),
    parser: str = typer.Option("auto", "--parser", "-p", help="解析器类型"),
    rule: Optional[str] = typer.Option(None, "--rule", "-r", help="指定规则名称（逗号分隔）"),
    no_notify: bool = typer.Option(False, "--no-notify", help="禁用通知"),
    format: str = typer.Option("rich", "--format", "-f", help="输出格式: rich/plain/json"),
    config_dir: Optional[str] = typer.Option(None, "--config-dir", help="配置目录路径"),
):
    """实时监控日志文件（类似 tail -f + 规则匹配）"""
    setup_logging()
    cfg_dir = Path(config_dir) if config_dir else None
    settings = load_settings(cfg_dir)

    from log_inspector.auth import require_permission
    require_permission(settings.auth)

    from log_inspector.scanner import auto_detect_parser, BUILTIN_PARSERS
    from log_inspector.watcher import RealtimeMonitor
    from log_inspector.watcher.display import print_match_rich, format_match

    db = _get_db(settings)
    rules = load_rules(cfg_dir)
    rule_names = [r.strip() for r in rule.split(",")] if rule else None

    target = Path(log_path)
    if not target.exists():
        console.print(f"[red]文件不存在: {target}[/red]")
        raise typer.Exit(1)

    if parser == "auto":
        selected_parser = auto_detect_parser(target)
    elif parser in BUILTIN_PARSERS:
        selected_parser = BUILTIN_PARSERS[parser]()
    else:
        selected_parser = auto_detect_parser(target)

    notifier = None
    if not no_notify and settings.notification.enabled:
        from log_inspector.notifier import NotificationDispatcher
        notifier = NotificationDispatcher(settings.notification)

    def on_match(entry, matched_rules):
        if format == "rich":
            print_match_rich(entry, matched_rules)
        else:
            output = format_match(entry, matched_rules, format)
            if output:
                console.print(output, highlight=False)

    monitor = RealtimeMonitor(
        db=db,
        settings=settings,
        parser=selected_parser,
        rules=rules,
        rule_names=rule_names,
        notifier=notifier,
        on_match=on_match,
    )
    monitor.start(target)


# ─── export ──────────────────────────────────────────────────────────────────

@app.command()
def export(
    scan_id: int = typer.Argument(..., help="扫描记录 ID"),
    format: str = typer.Option("json", "--format", "-f", help="导出格式: json/csv"),
    retry_id: Optional[int] = typer.Option(None, "--retry", help="重试失败的导出 (export_id)"),
):
    """导出扫描结果"""
    settings = load_settings()
    db = _get_db(settings)

    from log_inspector.exporter import Exporter
    exporter = Exporter(db, settings.export_dir)

    if retry_id:
        exporter.retry(retry_id)
    else:
        exporter.export(scan_id, format)


# ─── rules ───────────────────────────────────────────────────────────────────

@rules_app.command("list")
def rules_list(
    config_dir: Optional[str] = typer.Option(None, "--config-dir", help="配置目录路径"),
):
    """列出所有检测规则"""
    cfg_dir = Path(config_dir) if config_dir else None
    rules = load_rules(cfg_dir)

    from log_inspector.rules.builtin import BUILTIN_RULES
    all_rules = BUILTIN_RULES + rules

    table = Table(title="检测规则列表")
    table.add_column("名称", style="cyan")
    table.add_column("类型")
    table.add_column("级别")
    table.add_column("优先级", justify="right")
    table.add_column("范围")
    table.add_column("通知")
    table.add_column("状态")

    for r in all_rules:
        status = "[green]启用[/green]" if r.enabled else "[red]禁用[/red]"
        notify_status = "[green]是[/green]" if r.notify else "[dim]否[/dim]"
        table.add_row(r.name, r.type, r.level, str(r.priority), r.scope, notify_status, status)

    console.print(table)


@rules_app.command("check")
def rules_check(
    config_dir: Optional[str] = typer.Option(None, "--config-dir", help="配置目录路径"),
):
    """检测规则冲突"""
    cfg_dir = Path(config_dir) if config_dir else None
    rules = load_rules(cfg_dir)

    from log_inspector.rules.builtin import BUILTIN_RULES
    from log_inspector.rules.engine import RuleEngine

    all_rules = BUILTIN_RULES + rules
    engine = RuleEngine(all_rules)
    engine.print_conflicts()


@rules_app.command("add")
def rules_add(
    yaml_file: str = typer.Argument(..., help="包含新规则的 YAML 文件路径"),
):
    """从 YAML 文件添加规则"""
    path = Path(yaml_file)
    if not path.exists():
        console.print(f"[red]文件不存在: {path}[/red]")
        raise typer.Exit(1)

    data = load_yaml(path)
    validated = validate_config(data, RulesFile, str(path))
    console.print(f"[green]规则文件校验通过: {len(validated.rules)} 条规则[/green]")
    for r in validated.rules:
        console.print(f"  • {r.name} ({r.type}, {r.level})")


# ─── report ──────────────────────────────────────────────────────────────────

@report_app.command("slow-requests")
def report_slow(
    scan_id: Optional[int] = typer.Option(None, "--scan-id", help="指定扫描 ID"),
    limit: int = typer.Option(20, "--limit", "-n", help="显示条数"),
):
    """慢请求统计报告"""
    settings = load_settings()
    db = _get_db(settings)
    records = db.get_slow_requests(scan_id)

    if not records:
        console.print("[yellow]未找到慢请求记录[/yellow]")
        return

    table = Table(title="慢请求统计")
    table.add_column("路径", style="cyan")
    table.add_column("方法")
    table.add_column("响应时间(ms)", justify="right", style="red")
    table.add_column("状态码")
    table.add_column("时间")

    for r in records[:limit]:
        table.add_row(
            r["path"],
            r["method"],
            f"{r['response_time_ms']:.1f}",
            str(r["status_code"] or "-"),
            r["timestamp"] or "-",
        )

    console.print(table)
    console.print(f"\n共 {len(records)} 条慢请求记录")


@report_app.command("errors")
def report_errors(
    scan_id: Optional[int] = typer.Option(None, "--scan-id", help="指定扫描 ID"),
):
    """错误类型汇总"""
    settings = load_settings()
    db = _get_db(settings)
    summary = db.get_error_summary(scan_id)

    if not summary:
        console.print("[yellow]未找到错误记录[/yellow]")
        return

    table = Table(title="错误类型汇总")
    table.add_column("级别", style="red")
    table.add_column("规则")
    table.add_column("分类")
    table.add_column("数量", justify="right", style="bold")

    for r in summary:
        table.add_row(r["level"], r["rule_name"], r["category"], str(r["count"]))

    console.print(table)


# ─── schedule ────────────────────────────────────────────────────────────────

@schedule_app.command("list")
def schedule_list(
    config_dir: Optional[str] = typer.Option(None, "--config-dir", help="配置目录路径"),
):
    """查看定时任务配置"""
    cfg_dir = Path(config_dir) if config_dir else None
    tasks = load_tasks(cfg_dir)

    table = Table(title="定时巡检任务")
    table.add_column("名称", style="cyan")
    table.add_column("Cron 表达式")
    table.add_column("日志源")
    table.add_column("指定规则")
    table.add_column("状态")

    for t in tasks:
        status = "[green]启用[/green]" if t.enabled else "[red]禁用[/red]"
        table.add_row(
            t.name,
            t.cron,
            ", ".join(t.log_sources[:2]) + ("..." if len(t.log_sources) > 2 else ""),
            ", ".join(t.rules) if t.rules else "全部",
            status,
        )

    console.print(table)


@schedule_app.command("add")
def schedule_add(
    name: str = typer.Option(..., "--name", "-n", help="任务名称"),
    cron: str = typer.Option(..., "--cron", "-c", help="Cron 表达式"),
    sources: str = typer.Option(..., "--sources", "-s", help="日志源路径（逗号分隔）"),
    rules: Optional[str] = typer.Option(None, "--rules", "-r", help="规则名称（逗号分隔）"),
):
    """添加定时巡检任务"""
    console.print(f"[green]任务配置:[/green]")
    console.print(f"  名称: {name}")
    console.print(f"  Cron: {cron}")
    console.print(f"  日志源: {sources}")
    console.print(f"\n请将以下内容添加到 config/tasks.yaml:")
    console.print(f"""
  - name: {name}
    cron: "{cron}"
    log_sources:
{chr(10).join(f'      - "{s.strip()}"' for s in sources.split(','))}
    rules: [{rules or ''}]
    enabled: true
""")


@schedule_app.command("remove")
def schedule_remove(
    name: str = typer.Argument(..., help="要移除的任务名称"),
):
    """移除定时任务"""
    console.print(f"[yellow]请从 config/tasks.yaml 中移除任务: {name}[/yellow]")


@schedule_app.command("run")
def schedule_run(
    config_dir: Optional[str] = typer.Option(None, "--config-dir", help="配置目录路径"),
):
    """启动调度器守护进程"""
    setup_logging()
    cfg_dir = Path(config_dir) if config_dir else None
    settings = load_settings(cfg_dir)
    tasks = load_tasks(cfg_dir)

    from log_inspector.auth import require_permission
    require_permission(settings.auth)

    from log_inspector.scheduler import ScheduleManager

    db = _get_db(settings)
    manager = ScheduleManager(db, cfg_dir)

    enabled_tasks = [t for t in tasks if t.enabled]
    if not enabled_tasks:
        console.print("[yellow]没有启用的定时任务[/yellow]")
        raise typer.Exit(0)

    for task in enabled_tasks:
        manager.add_task(task)

    manager.start()
    console.print(f"\n[blue]调度器运行中 ({len(enabled_tasks)} 个任务)，按 Ctrl+C 停止...[/blue]")

    def _shutdown(signum, frame):
        manager.shutdown()
        raise typer.Exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        manager.shutdown()


# ─── config ──────────────────────────────────────────────────────────────────

@config_app.command("check")
def config_check(
    config_dir: Optional[str] = typer.Option(None, "--config-dir", help="配置目录路径"),
):
    """校验所有 YAML 配置文件"""
    cfg_dir = Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR
    all_ok = True
    checked = 0

    check_items = [
        ("settings.yaml", Settings),
        ("rules.yaml", RulesFile),
        ("tasks.yaml", TasksFile),
        ("projects.yaml", ProjectRegistry),
    ]

    for name, model in check_items:
        path = cfg_dir / name
        if not path.exists():
            continue

        checked += 1
        data, yaml_errors = try_load_yaml(path)
        if yaml_errors:
            all_ok = False
            console.print(f"[red]✗ {name}[/red]")
            for err in yaml_errors:
                console.print(f"    {err}", highlight=False, markup=False)
            continue

        result, val_errors = try_validate_config(data, model)
        if val_errors:
            all_ok = False
            console.print(f"[red]✗ {name}[/red]")
            for err in val_errors:
                console.print(f"    {err}", highlight=False, markup=False)
        else:
            console.print(f"[green]✓ {name}[/green]")

    console.print()
    if checked == 0:
        console.print(f"[yellow]配置目录中没有可检查的文件: {cfg_dir}[/yellow]")
        raise typer.Exit(1)
    elif all_ok:
        console.print(f"[green]所有配置校验通过 ({checked} 个文件)[/green]")
    else:
        console.print("[red]存在配置错误，请按上方提示修复[/red]")
        raise typer.Exit(1)


@config_app.command("show")
def config_show(
    config_dir: Optional[str] = typer.Option(None, "--config-dir", help="配置目录路径"),
):
    """显示当前配置"""
    cfg_dir = Path(config_dir) if config_dir else None
    settings = load_settings(cfg_dir)
    console.print_json(settings.model_dump_json(indent=2))


# ─── plugin ──────────────────────────────────────────────────────────────────

@plugin_app.command("list")
def plugin_list():
    """列出已加载的插件"""
    settings = load_settings()
    from log_inspector.plugins import PluginLoader
    loader = PluginLoader(settings.plugin_dir)
    parsers = loader.load_all()

    if not parsers:
        console.print("[yellow]未加载任何插件[/yellow]")
        console.print(f"  插件目录: {settings.plugin_dir}")
        return

    table = Table(title="已加载插件")
    table.add_column("名称", style="cyan")
    table.add_column("描述")

    for p in parsers:
        table.add_row(p.name, p.description)

    console.print(table)


# ─── notify ──────────────────────────────────────────────────────────────────

@notify_app.command("test")
def notify_test(
    channel: Optional[str] = typer.Option(None, "--channel", "-c", help="测试指定渠道"),
    config_dir: Optional[str] = typer.Option(None, "--config-dir", help="配置目录路径"),
):
    """测试通知渠道配置"""
    cfg_dir = Path(config_dir) if config_dir else None
    settings = load_settings(cfg_dir)

    if not settings.notification.enabled:
        console.print("[yellow]通知功能未启用，请在 settings.yaml 中设置 notification.enabled: true[/yellow]")
        raise typer.Exit(1)

    from log_inspector.notifier import NotificationDispatcher, NotifyEvent

    dispatcher = NotificationDispatcher(settings.notification)
    event = NotifyEvent(
        rule_name="test_notification",
        level="error",
        message="这是一条测试通知，验证通知渠道配置是否正确。",
    )

    channels_to_test = [channel] if channel else settings.notification.channels
    results = []
    for ch_name in channels_to_test:
        ch = dispatcher._channels.get(ch_name)
        if ch is None:
            results.append((ch_name, False, "渠道未配置或未启用"))
            continue
        try:
            ok = ch.send(event)
            results.append((ch_name, ok, "发送成功" if ok else "发送失败"))
        except Exception as e:
            results.append((ch_name, False, str(e)))

    table = Table(title="通知渠道测试结果")
    table.add_column("渠道", style="cyan")
    table.add_column("状态")
    table.add_column("详情")

    for name, ok, msg in results:
        status = "[green]通过[/green]" if ok else "[red]失败[/red]"
        table.add_row(name, status, msg)

    console.print(table)


@notify_app.command("history")
def notify_history(
    scan_id: Optional[int] = typer.Option(None, "--scan-id", help="指定扫描 ID"),
):
    """查看通知发送历史"""
    settings = load_settings()
    db = _get_db(settings)
    records = db.get_notifications(scan_id)

    if not records:
        console.print("[yellow]暂无通知记录[/yellow]")
        return

    table = Table(title="通知发送历史")
    table.add_column("ID", justify="right")
    table.add_column("规则")
    table.add_column("渠道")
    table.add_column("状态")
    table.add_column("时间")

    for r in records[:50]:
        table.add_row(
            str(r["id"]),
            r["rule_name"],
            r["channel"],
            r["status"],
            r["sent_at"] or "-",
        )

    console.print(table)


# ─── remote ──────────────────────────────────────────────────────────────────

@remote_app.command("list")
def remote_list(
    config_dir: Optional[str] = typer.Option(None, "--config-dir", help="配置目录路径"),
):
    """列出已配置的远程日志源"""
    cfg_dir = Path(config_dir) if config_dir else None
    settings = load_settings(cfg_dir)

    if not settings.remote_sources:
        console.print("[yellow]未配置远程日志源[/yellow]")
        console.print("  请在 settings.yaml 中添加 remote_sources 配置")
        return

    table = Table(title="远程日志源")
    table.add_column("名称", style="cyan")
    table.add_column("类型")
    table.add_column("远程路径")
    table.add_column("解析器")

    for src in settings.remote_sources:
        table.add_row(src.name, src.type, src.remote_path, src.parser)

    console.print(table)


@remote_app.command("test")
def remote_test(
    name: str = typer.Argument(..., help="远程源名称"),
    config_dir: Optional[str] = typer.Option(None, "--config-dir", help="配置目录路径"),
):
    """测试远程日志源连接"""
    cfg_dir = Path(config_dir) if config_dir else None
    settings = load_settings(cfg_dir)

    source = None
    for src in settings.remote_sources:
        if src.name == name:
            source = src
            break

    if source is None:
        console.print(f"[red]远程源不存在: {name}[/red]")
        raise typer.Exit(1)

    from log_inspector.remote import RemoteSourceResolver
    resolver = RemoteSourceResolver()

    console.print(f"[blue]测试连接: {name} ({source.type})...[/blue]")
    ok = resolver.test_connection(source)
    if ok:
        console.print(f"[green]连接成功: {name}[/green]")
    else:
        console.print(f"[red]连接失败: {name}[/red]")
        raise typer.Exit(1)


@remote_app.command("scan")
def remote_scan(
    name: str = typer.Argument(..., help="远程源名称"),
    rule: Optional[str] = typer.Option(None, "--rule", "-r", help="指定规则名称（逗号分隔）"),
    config_dir: Optional[str] = typer.Option(None, "--config-dir", help="配置目录路径"),
):
    """扫描远程日志源"""
    setup_logging()
    cfg_dir = Path(config_dir) if config_dir else None
    settings = load_settings(cfg_dir)

    source = None
    for src in settings.remote_sources:
        if src.name == name:
            source = src
            break

    if source is None:
        console.print(f"[red]远程源不存在: {name}[/red]")
        raise typer.Exit(1)

    from log_inspector.auth import require_permission
    require_permission(settings.auth)

    from log_inspector.scanner import Scanner

    db = _get_db(settings)
    rules = load_rules(cfg_dir)
    rule_names = [r.strip() for r in rule.split(",")] if rule else None

    scanner = Scanner(db, settings)
    scanner.scan_remote(source, rules=rules, rule_names=rule_names)


# ─── project ─────────────────────────────────────────────────────────────────

@project_app.command("list")
def project_list(
    config_dir: Optional[str] = typer.Option(None, "--config-dir", help="配置目录路径"),
):
    """列出所有项目"""
    cfg_dir = Path(config_dir) if config_dir else None
    registry = load_projects(cfg_dir)

    table = Table(title="项目列表")
    table.add_column("ID", style="cyan")
    table.add_column("名称")
    table.add_column("描述")
    table.add_column("默认")
    table.add_column("状态")

    for p in registry.projects:
        is_default = "[green]★[/green]" if p.project_id == registry.default_project else ""
        status = "[green]活跃[/green]" if p.active else "[red]禁用[/red]"
        table.add_row(p.project_id, p.name, p.description, is_default, status)

    console.print(table)


@project_app.command("create")
def project_create(
    project_id: str = typer.Argument(..., help="项目 ID"),
    name: str = typer.Option(..., "--name", "-n", help="项目名称"),
    description: str = typer.Option("", "--desc", "-d", help="项目描述"),
    config_dir: Optional[str] = typer.Option(None, "--config-dir", help="配置目录路径"),
):
    """创建新项目"""
    cfg_dir = Path(config_dir) if config_dir else None
    from log_inspector.projects import ProjectManager
    manager = ProjectManager(cfg_dir)

    try:
        manager.create_project(project_id, name, description)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@project_app.command("switch")
def project_switch(
    project_id: str = typer.Argument(..., help="要切换到的项目 ID"),
    config_dir: Optional[str] = typer.Option(None, "--config-dir", help="配置目录路径"),
):
    """切换默认项目"""
    cfg_dir = Path(config_dir) if config_dir else None
    from log_inspector.projects import ProjectManager
    manager = ProjectManager(cfg_dir)

    try:
        manager.switch_default(project_id)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@project_app.command("info")
def project_info(
    project_id: Optional[str] = typer.Argument(None, help="项目 ID（默认当前项目）"),
    config_dir: Optional[str] = typer.Option(None, "--config-dir", help="配置目录路径"),
):
    """查看项目详情"""
    cfg_dir = Path(config_dir) if config_dir else None
    from log_inspector.projects import ProjectManager
    manager = ProjectManager(cfg_dir)

    pid = project_id or manager.default_project
    project = manager.get_project(pid)
    if not project:
        console.print(f"[red]项目不存在: {pid}[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]项目: {project.name}[/bold]")
    console.print(f"  ID: {project.project_id}")
    console.print(f"  描述: {project.description or '-'}")
    console.print(f"  配置目录: {project.config_dir or '默认'}")
    console.print(f"  数据库: {project.database_path or '默认'}")
    console.print(f"  允许用户: {', '.join(project.allowed_users) or '全部'}")
    console.print(f"  状态: {'活跃' if project.active else '禁用'}")


@project_app.command("delete")
def project_delete(
    project_id: str = typer.Argument(..., help="要删除的项目 ID"),
    remove_files: bool = typer.Option(False, "--remove-files", help="同时删除配置文件"),
    config_dir: Optional[str] = typer.Option(None, "--config-dir", help="配置目录路径"),
):
    """删除项目"""
    cfg_dir = Path(config_dir) if config_dir else None
    from log_inspector.projects import ProjectManager
    manager = ProjectManager(cfg_dir)

    try:
        manager.delete_project(project_id, remove_files=remove_files)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
