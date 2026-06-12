"""解析器测试"""

from datetime import datetime

from log_inspector.parsers.nginx import NginxParser
from log_inspector.parsers.node import NodeParser
from log_inspector.parsers.python_log import PythonLogParser


class TestNginxParser:
    def setup_method(self):
        self.parser = NginxParser()

    def test_parse_combined_log(self):
        line = '192.168.1.1 - - [10/Jun/2026:10:00:01 +0800] "GET /api/users HTTP/1.1" 200 1234 "-" "Mozilla/5.0" 0.052'
        entry = self.parser.parse_line(line, 1)
        assert entry is not None
        assert entry.level == "info"
        assert entry.metadata["status_code"] == 200
        assert entry.metadata["method"] == "GET"
        assert entry.metadata["path"] == "/api/users"
        assert abs(entry.metadata["response_time_ms"] - 52.0) < 0.1

    def test_parse_5xx(self):
        line = '10.0.0.1 - - [10/Jun/2026:10:00:00 +0800] "GET /error HTTP/1.1" 502 0 "-" "curl"'
        entry = self.parser.parse_line(line, 1)
        assert entry is not None
        assert entry.level == "error"
        assert entry.metadata["status_code"] == 502

    def test_parse_4xx(self):
        line = '10.0.0.1 - - [10/Jun/2026:10:00:00 +0800] "GET /secret HTTP/1.1" 403 0 "-" "curl"'
        entry = self.parser.parse_line(line, 1)
        assert entry is not None
        assert entry.level == "warning"

    def test_parse_error_log(self):
        line = '2026/06/10 10:00:00 [error] 1234#0: *5678 connect() failed'
        entry = self.parser.parse_line(line, 1)
        assert entry is not None
        assert entry.level == "error"

    def test_empty_line(self):
        assert self.parser.parse_line("", 1) is None

    def test_malformed_line(self):
        assert self.parser.parse_line("this is not a log line", 1) is None

    def test_can_parse(self):
        lines = [
            '192.168.1.1 - - [10/Jun/2026:10:00:01 +0800] "GET / HTTP/1.1" 200 100 "-" "Mozilla"',
            '192.168.1.2 - - [10/Jun/2026:10:00:02 +0800] "POST /api HTTP/1.1" 201 50 "-" "curl"',
        ]
        assert self.parser.can_parse(lines)


class TestNodeParser:
    def setup_method(self):
        self.parser = NodeParser()

    def test_parse_json_info(self):
        line = '{"level":"info","message":"Server started","timestamp":"2026-06-10T10:00:00.000Z"}'
        entry = self.parser.parse_line(line, 1)
        assert entry is not None
        assert entry.level == "info"
        assert entry.message == "Server started"

    def test_parse_json_error(self):
        line = '{"level":"error","message":"Connection refused","timestamp":"2026-06-10T10:00:00.000Z","code":"ECONNREFUSED"}'
        entry = self.parser.parse_line(line, 1)
        assert entry is not None
        assert entry.level == "error"
        assert "code" in entry.metadata

    def test_parse_json_with_response_time(self):
        line = '{"level":"info","message":"Request done","timestamp":"2026-06-10T10:00:00.000Z","responseTime":1500}'
        entry = self.parser.parse_line(line, 1)
        assert entry is not None
        assert entry.metadata["response_time_ms"] == 1500.0

    def test_parse_text_format(self):
        line = "2026-06-10T10:00:00.000Z [ERROR] Something failed"
        entry = self.parser.parse_line(line, 1)
        assert entry is not None
        assert entry.level == "error"

    def test_parse_pm2_format(self):
        line = "0|app  | 2026-06-10T10:00:00.000Z: Worker started"
        entry = self.parser.parse_line(line, 1)
        assert entry is not None
        assert "Worker started" in entry.message

    def test_empty_line(self):
        assert self.parser.parse_line("", 1) is None

    def test_invalid_json(self):
        assert self.parser.parse_line("{invalid json", 1) is None


class TestPythonLogParser:
    def setup_method(self):
        self.parser = PythonLogParser()

    def test_parse_standard_format(self):
        line = "2026-06-10 10:00:00,123 - django.request - ERROR - Internal Server Error"
        entry = self.parser.parse_line(line, 1)
        assert entry is not None
        assert entry.level == "error"
        assert entry.metadata["module"] == "django.request"

    def test_parse_bracket_format(self):
        line = "[2026-06-10 10:00:00] ERROR in app: Something went wrong"
        entry = self.parser.parse_line(line, 1)
        assert entry is not None
        assert entry.level == "error"

    def test_parse_traceback(self):
        self.parser._in_traceback = False
        line = "Traceback (most recent call last):"
        entry = self.parser.parse_line(line, 1)
        assert entry is not None
        assert entry.level == "error"
        assert self.parser._in_traceback is True

    def test_parse_exception_line(self):
        self.parser._in_traceback = True
        line = "ValueError: Invalid payment amount"
        entry = self.parser.parse_line(line, 1)
        assert entry is not None
        assert entry.metadata["exception_type"] == "ValueError"
        assert self.parser._in_traceback is False

    def test_traceback_continuation_skipped(self):
        self.parser._in_traceback = True
        line = '  File "/app/views.py", line 42, in checkout'
        entry = self.parser.parse_line(line, 1)
        assert entry is None

    def test_response_time_in_message(self):
        line = "2026-06-10 10:00:00,000 - gunicorn - INFO - GET /api 200 took 3500ms"
        entry = self.parser.parse_line(line, 1)
        assert entry is not None
        assert entry.metadata.get("response_time_ms") == 3500.0

    def test_empty_line(self):
        assert self.parser.parse_line("", 1) is None
