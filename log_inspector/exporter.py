"""导出模块：JSON/CSV + 失败追踪 + 重试"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from rich.console import Console

from log_inspector.db import Database

console = Console(stderr=True)


class Exporter:
    def __init__(self, db: Database, export_dir: str = "exports"):
        self.db = db
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def export(self, scan_id: int, fmt: str = "json") -> Path:
        """导出扫描结果，返回输出文件路径"""
        scan = self.db.get_scan(scan_id)
        if not scan:
            raise ValueError(f"扫描记录不存在: scan_id={scan_id}")

        filename = f"scan_{scan_id}_{fmt}.{fmt}"
        output_path = self.export_dir / filename

        export_id = self.db.create_export(scan_id, fmt, str(output_path))

        try:
            findings = self.db.get_findings(scan_id)
            slow_requests = self.db.get_slow_requests(scan_id)

            if fmt == "json":
                self._export_json(output_path, scan, findings, slow_requests)
            elif fmt == "csv":
                self._export_csv(output_path, findings, slow_requests)
            else:
                raise ValueError(f"不支持的导出格式: {fmt}")

            self.db.update_export(export_id, "success")
            console.print(f"[green]导出成功:[/green] {output_path}")
            return output_path

        except Exception as e:
            self.db.update_export(export_id, "failed", str(e))
            console.print(f"[red]导出失败 (export_id={export_id}): {e}[/red]")
            raise

    def retry(self, export_id: int) -> Path:
        """重试失败的导出"""
        export_record = self.db.get_export(export_id)
        if not export_record:
            raise ValueError(f"导出记录不存在: export_id={export_id}")
        if export_record["status"] != "failed":
            raise ValueError(f"只能重试失败的导出，当前状态: {export_record['status']}")

        console.print(f"[yellow]重试导出 export_id={export_id}...[/yellow]")
        return self.export(export_record["scan_id"], export_record["format"])

    def _export_json(self, path: Path, scan: dict, findings: list[dict], slow_requests: list[dict]):
        data = {
            "scan": scan,
            "findings": findings,
            "slow_requests": slow_requests,
            "summary": {
                "total_findings": len(findings),
                "total_slow_requests": len(slow_requests),
                "by_level": self._count_by_key(findings, "level"),
                "by_category": self._count_by_key(findings, "category"),
                "by_rule": self._count_by_key(findings, "rule_name"),
            },
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    def _export_csv(self, path: Path, findings: list[dict], slow_requests: list[dict]):
        findings_path = path.with_name(path.stem + "_findings.csv")
        slow_path = path.with_name(path.stem + "_slow_requests.csv")

        if findings:
            with open(findings_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=findings[0].keys())
                writer.writeheader()
                writer.writerows(findings)

        if slow_requests:
            with open(slow_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=slow_requests[0].keys())
                writer.writeheader()
                writer.writerows(slow_requests)

        # Also write a summary CSV at the main path
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["类型", "数量"])
            writer.writerow(["匹配结果", len(findings)])
            writer.writerow(["慢请求", len(slow_requests)])
            by_level = self._count_by_key(findings, "level")
            for level, count in by_level.items():
                writer.writerow([f"级别-{level}", count])

    def _count_by_key(self, records: list[dict], key: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in records:
            val = r.get(key, "unknown")
            counts[val] = counts.get(val, 0) + 1
        return counts
