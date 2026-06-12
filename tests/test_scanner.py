"""扫描引擎测试"""

from pathlib import Path

from log_inspector.config import Settings, SlowRequestThreshold, AuthConfig
from log_inspector.db import Database
from log_inspector.scanner import Scanner, auto_detect_parser


class TestAutoDetect:
    def test_detect_nginx(self, sample_nginx_log):
        parser = auto_detect_parser(sample_nginx_log)
        assert parser.name == "nginx"

    def test_detect_node(self, sample_node_log):
        parser = auto_detect_parser(sample_node_log)
        assert parser.name == "node"

    def test_detect_python(self, sample_python_log):
        parser = auto_detect_parser(sample_python_log)
        assert parser.name == "python"


class TestScanner:
    def test_scan_nginx(self, db, settings, sample_nginx_log):
        scanner = Scanner(db, settings)
        scan_id = scanner.scan(sample_nginx_log, parser_type="nginx")
        assert scan_id > 0

        scan = db.get_scan(scan_id)
        assert scan["status"] == "completed"
        assert scan["total_lines"] > 0

    def test_scan_node(self, db, settings, sample_node_log):
        scanner = Scanner(db, settings)
        scan_id = scanner.scan(sample_node_log, parser_type="node")
        assert scan_id > 0

        scan = db.get_scan(scan_id)
        assert scan["status"] == "completed"

    def test_scan_python(self, db, settings, sample_python_log):
        scanner = Scanner(db, settings)
        scan_id = scanner.scan(sample_python_log, parser_type="python")
        assert scan_id > 0

        scan = db.get_scan(scan_id)
        assert scan["status"] == "completed"

    def test_scan_finds_errors(self, db, settings, sample_nginx_log):
        scanner = Scanner(db, settings)
        scan_id = scanner.scan(sample_nginx_log, parser_type="nginx")

        findings = db.get_findings(scan_id)
        assert len(findings) > 0
        error_findings = [f for f in findings if f["level"] == "error"]
        assert len(error_findings) > 0

    def test_scan_finds_slow_requests(self, db, settings, sample_nginx_log):
        scanner = Scanner(db, settings)
        scan_id = scanner.scan(sample_nginx_log, parser_type="nginx")

        slow = db.get_slow_requests(scan_id)
        assert len(slow) > 0
        assert all(r["response_time_ms"] >= 1000.0 for r in slow)

    def test_scan_nonexistent_file(self, db, settings, tmp_path):
        scanner = Scanner(db, settings)
        try:
            scanner.scan(tmp_path / "nonexistent.log")
            assert False, "Should have raised"
        except FileNotFoundError:
            pass

    def test_scan_with_time_filter(self, db, settings, sample_nginx_log):
        from datetime import datetime
        scanner = Scanner(db, settings)
        scan_id = scanner.scan(
            sample_nginx_log,
            parser_type="nginx",
            start_time=datetime(2026, 6, 10, 10, 0, 3),
            end_time=datetime(2026, 6, 10, 10, 0, 6),
        )
        scan = db.get_scan(scan_id)
        assert scan["status"] == "completed"
        # 应该只命中 10:00:03 ~ 10:00:06 范围内的行
        assert scan["total_lines"] > 0

    def test_scan_time_filter_with_timezone_nginx(self, db, settings, tmp_path):
        """带时区的 Nginx 日志 + naive datetime 过滤，不能 TypeError"""
        content = (
            '1.1.1.1 - - [10/Jun/2026:09:59:59 +0800] "GET /before HTTP/1.1" 200 10 "-" "ua" 0.01\n'
            '1.1.1.1 - - [10/Jun/2026:10:00:01 +0800] "GET /inside HTTP/1.1" 500 10 "-" "ua" 0.02\n'
            '1.1.1.1 - - [10/Jun/2026:10:00:05 +0800] "GET /also-inside HTTP/1.1" 502 10 "-" "ua" 3.5\n'
            '1.1.1.1 - - [10/Jun/2026:10:00:10 +0800] "GET /after HTTP/1.1" 200 10 "-" "ua" 0.01\n'
        )
        log_file = tmp_path / "tz_access.log"
        log_file.write_text(content, encoding="utf-8")

        from datetime import datetime
        scanner = Scanner(db, settings)
        scan_id = scanner.scan(
            log_file,
            parser_type="nginx",
            start_time=datetime(2026, 6, 10, 10, 0, 0),
            end_time=datetime(2026, 6, 10, 10, 0, 6),
        )
        scan = db.get_scan(scan_id)
        assert scan["status"] == "completed"

        # 只有 /inside 和 /also-inside 在时间范围内
        findings = db.get_findings(scan_id)
        paths_found = [f["message"] for f in findings]
        assert any("inside" in p for p in paths_found)
        assert not any("before" in p for p in paths_found)
        assert not any("after" in p for p in paths_found)

    def test_scan_time_filter_full_pipeline(self, db, settings, tmp_path):
        """端到端验证：扫描→落库→统计→导出，时区日志不中断"""
        content = (
            '2.2.2.2 - - [10/Jun/2026:10:00:02 +0800] "GET /api/slow HTTP/1.1" 200 100 "-" "ua" 8.0\n'
            '2.2.2.2 - - [10/Jun/2026:10:00:03 +0800] "POST /api/pay HTTP/1.1" 500 50 "-" "ua" 0.5\n'
        )
        log_file = tmp_path / "pipeline.log"
        log_file.write_text(content, encoding="utf-8")

        from datetime import datetime
        scanner = Scanner(db, settings)
        scan_id = scanner.scan(
            log_file,
            parser_type="nginx",
            start_time=datetime(2026, 6, 10, 10, 0, 0),
            end_time=datetime(2026, 6, 10, 10, 0, 5),
        )

        # 落库正确
        assert db.get_scan(scan_id)["status"] == "completed"
        # 慢请求统计正常
        slow = db.get_slow_requests(scan_id)
        assert len(slow) == 1
        assert slow[0]["response_time_ms"] == 8000.0
        # 错误汇总正常
        summary = db.get_error_summary(scan_id)
        assert any(s["level"] == "error" for s in summary)

        # 导出不中断
        from log_inspector.exporter import Exporter
        exporter = Exporter(db, str(tmp_path / "exports"))
        output = exporter.export(scan_id, "json")
        assert output.exists()

    def test_scan_encoding_fallback(self, db, settings, tmp_path):
        # Write a file with GBK encoding
        content = "2026-06-10 10:00:00,000 - app - ERROR - 数据库连接失败\n"
        log_file = tmp_path / "gbk.log"
        log_file.write_bytes(content.encode("gbk"))

        scanner = Scanner(db, settings)
        scan_id = scanner.scan(log_file, parser_type="python")
        scan = db.get_scan(scan_id)
        assert scan["status"] == "completed"
