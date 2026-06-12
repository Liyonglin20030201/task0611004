"""APScheduler 定时任务管理 + 防重复锁"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from rich.console import Console

from log_inspector.config import TaskConfig, load_rules, load_settings
from log_inspector.db import Database

console = Console(stderr=True)


class ScheduleManager:
    def __init__(self, db: Database, config_dir: Path | None = None):
        self.db = db
        self.config_dir = config_dir
        self.scheduler = BackgroundScheduler()
        self._jobs: dict[str, TaskConfig] = {}

    def add_task(self, task: TaskConfig):
        """注册定时任务"""
        if task.name in self._jobs:
            console.print(f"[yellow]任务已存在: {task.name}[/yellow]")
            return

        trigger = self._parse_cron(task.cron)
        self.scheduler.add_job(
            self._execute_task,
            trigger=trigger,
            args=[task],
            id=task.name,
            name=task.name,
            replace_existing=True,
        )
        self._jobs[task.name] = task
        console.print(f"[green]任务已注册: {task.name} ({task.cron})[/green]")

    def remove_task(self, task_name: str):
        """移除定时任务"""
        if task_name in self._jobs:
            self.scheduler.remove_job(task_name)
            del self._jobs[task_name]
            console.print(f"[green]任务已移除: {task_name}[/green]")
        else:
            console.print(f"[red]任务不存在: {task_name}[/red]")

    def list_tasks(self) -> list[dict]:
        """列出所有已注册的任务，基于内部注册表（不依赖 scheduler job store 状态）"""
        result = []
        for name, task in self._jobs.items():
            next_run = "未调度"
            try:
                job = self.scheduler.get_job(name)
                if job and hasattr(job, "next_run_time") and job.next_run_time:
                    next_run = str(job.next_run_time)
            except Exception:
                pass
            result.append({
                "name": name,
                "cron": task.cron,
                "log_sources": task.log_sources,
                "enabled": task.enabled,
                "next_run": next_run,
            })
        return result

    def start(self):
        """启动调度器"""
        self.scheduler.start()
        console.print("[green]调度器已启动[/green]")

    def shutdown(self):
        """关闭调度器"""
        self.scheduler.shutdown()
        console.print("[yellow]调度器已停止[/yellow]")

    def _execute_task(self, task: TaskConfig):
        """执行巡检任务（带防重复锁）"""
        time_window = datetime.now().strftime("%Y%m%d%H%M")

        if not self.db.acquire_schedule_lock(task.name, time_window):
            console.print(f"[yellow]跳过重复执行: {task.name} ({time_window})[/yellow]")
            return

        try:
            from log_inspector.scanner import Scanner
            settings = load_settings(self.config_dir)
            rules = load_rules(self.config_dir)

            scanner = Scanner(self.db, settings)
            for source in task.log_sources:
                log_path = Path(source)
                if log_path.exists():
                    scanner.scan(
                        log_path=log_path,
                        rules=rules,
                        rule_names=task.rules if task.rules else None,
                    )
                else:
                    console.print(f"[yellow]日志文件不存在，跳过: {source}[/yellow]")

            self.db.release_schedule_lock(task.name, time_window, "completed")
        except Exception as e:
            self.db.release_schedule_lock(task.name, time_window, "failed")
            console.print(f"[red]任务执行失败 [{task.name}]: {e}[/red]")

    def _parse_cron(self, cron_expr: str) -> CronTrigger:
        """解析 cron 表达式为 APScheduler trigger"""
        parts = cron_expr.split()
        if len(parts) == 5:
            return CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4],
            )
        elif len(parts) == 6:
            return CronTrigger(
                second=parts[0],
                minute=parts[1],
                hour=parts[2],
                day=parts[3],
                month=parts[4],
                day_of_week=parts[5],
            )
        raise ValueError(f"无效的 cron 表达式: {cron_expr}")
