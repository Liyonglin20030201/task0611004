"""导出模块测试"""

import json
from pathlib import Path

from log_inspector.db import Database
from log_inspector.exporter import Exporter


class TestExporter:
    def _setup_scan_data(self, db: Database) -> int:
        scan_id = db.create_scan("/tmp/test.log", "nginx")
        db.insert_findings_batch([
            {
                "scan_id": scan_id, "line_number": 1, "timestamp": "2026-06-10T10:00:00",
                "level": "error", "rule_name": "http_5xx", "category": "error",
                "message": "GET /api 500", "raw_line": "...", "metadata": "{}",
            },
            {
                "scan_id": scan_id, "line_number": 5, "timestamp": "2026-06-10T10:00:05",
                "level": "warning", "rule_name": "slow_request", "category": "slow_request",
                "message": "GET /api/slow 200", "raw_line": "...", "metadata": "{}",
            },
        ])
        db.insert_slow_requests_batch([
            {
                "scan_id": scan_id, "path": "/api/slow", "method": "GET",
                "response_time_ms": 3500.0, "status_code": 200, "timestamp": "2026-06-10T10:00:05",
            },
        ])
        db.update_scan(scan_id, "completed", 100, 2)
        return scan_id

    def test_export_json(self, db, tmp_path):
        scan_id = self._setup_scan_data(db)
        exporter = Exporter(db, str(tmp_path / "exports"))
        output = exporter.export(scan_id, "json")

        assert output.exists()
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["summary"]["total_findings"] == 2
        assert data["summary"]["total_slow_requests"] == 1

    def test_export_csv(self, db, tmp_path):
        scan_id = self._setup_scan_data(db)
        exporter = Exporter(db, str(tmp_path / "exports"))
        output = exporter.export(scan_id, "csv")

        assert output.exists()
        content = output.read_text(encoding="utf-8")
        assert "匹配结果" in content

    def test_export_invalid_scan(self, db, tmp_path):
        exporter = Exporter(db, str(tmp_path / "exports"))
        try:
            exporter.export(9999, "json")
            assert False, "Should have raised"
        except ValueError:
            pass

    def test_export_failure_tracked(self, db, tmp_path):
        scan_id = self._setup_scan_data(db)
        exporter = Exporter(db, str(tmp_path / "exports"))
        try:
            exporter.export(scan_id, "invalid_format")
        except ValueError:
            pass

        failed = db.get_failed_exports()
        assert len(failed) == 1
        assert "不支持" in failed[0]["error_message"]

    def test_retry_failed_export(self, db, tmp_path):
        scan_id = self._setup_scan_data(db)
        exporter = Exporter(db, str(tmp_path / "exports"))

        # First export as json succeeds
        exporter.export(scan_id, "json")

        # Manually mark an export as failed for retry test
        export_id = db.create_export(scan_id, "json", str(tmp_path / "exports" / "retry.json"))
        db.update_export(export_id, "failed", "simulated failure")

        output = exporter.retry(export_id)
        assert output.exists()
