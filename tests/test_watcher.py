"""实时监控测试"""

import threading
import time
from pathlib import Path

import pytest

from log_inspector.config import Settings, SlowRequestThreshold, AuthConfig, WatchConfig, RuleConfig
from log_inspector.db import Database
from log_inspector.parsers.nginx import NginxParser
from log_inspector.watcher.tail import FileTailer
from log_inspector.watcher.monitor import RealtimeMonitor


class TestFileTailer:
    def test_detects_new_lines(self, tmp_path):
        log_file = tmp_path / "test.log"
        log_file.write_text("line1\nline2\n", encoding="utf-8")

        tailer = FileTailer(log_file, poll_interval_ms=50, from_end=True)
        # Simulate _seek_to_end (which follow() calls internally)
        tailer._seek_to_end()

        # Append new content
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("line3\nline4\n")

        lines = tailer._read_new_lines()
        assert lines == ["line3", "line4"]

    def test_from_beginning(self, tmp_path):
        log_file = tmp_path / "test.log"
        log_file.write_text("first\nsecond\n", encoding="utf-8")

        tailer = FileTailer(log_file, poll_interval_ms=50, from_end=False)
        lines = tailer._read_new_lines()
        assert "first" in lines
        assert "second" in lines

    def test_file_rotation_detection(self, tmp_path):
        log_file = tmp_path / "test.log"
        log_file.write_text("old content\n" * 100, encoding="utf-8")

        tailer = FileTailer(log_file, poll_interval_ms=50, from_end=True)
        tailer._seek_to_end()  # position is now at end of 100 lines

        # Simulate rotation: truncate file (new file is smaller)
        log_file.write_text("new\n", encoding="utf-8")

        assert tailer._file_rotated() is True

    def test_handles_nonexistent_file(self, tmp_path):
        log_file = tmp_path / "nonexistent.log"
        tailer = FileTailer(log_file, poll_interval_ms=50)
        lines = tailer._read_new_lines()
        assert lines == []

    def test_follow_yields_new_lines(self, tmp_path):
        log_file = tmp_path / "follow.log"
        log_file.write_text("initial\n", encoding="utf-8")

        tailer = FileTailer(log_file, poll_interval_ms=50, from_end=True)

        collected = []

        def _follow():
            for line in tailer.follow():
                collected.append(line)
                if len(collected) >= 3:
                    break

        t = threading.Thread(target=_follow, daemon=True)
        t.start()

        time.sleep(0.1)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("appended1\n")
            f.write("appended2\n")
            f.write("appended3\n")

        t.join(timeout=3)
        assert len(collected) >= 3
        assert "appended1" in collected


class TestRealtimeMonitor:
    def test_process_line_matches(self, tmp_path):
        db = Database(tmp_path / "test.db")
        settings = Settings(
            database_path=str(tmp_path / "test.db"),
            batch_size=100,
            slow_request=SlowRequestThreshold(warning_ms=1000.0, critical_ms=5000.0),
            auth=AuthConfig(enabled=False),
            watch=WatchConfig(poll_interval_ms=50),
        )

        rules = [
            RuleConfig(name="test_5xx", type="regex", pattern=r"\s5\d{2}\s", level="error", priority=10),
        ]

        matches = []

        def on_match(entry, matched_rules):
            matches.append((entry, matched_rules))

        monitor = RealtimeMonitor(
            db=db,
            settings=settings,
            parser=NginxParser(),
            rules=rules,
            on_match=on_match,
        )

        # Process a line that should match
        line = '1.1.1.1 - - [10/Jun/2026:10:00:01 +0800] "GET /err HTTP/1.1" 500 50 "-" "ua" 0.1'
        monitor._process_line(line)

        assert len(matches) == 1
        assert matches[0][1][0].name == "test_5xx"

    def test_process_line_no_match(self, tmp_path):
        db = Database(tmp_path / "test.db")
        settings = Settings(
            database_path=str(tmp_path / "test.db"),
            batch_size=100,
            slow_request=SlowRequestThreshold(warning_ms=1000.0, critical_ms=5000.0),
            auth=AuthConfig(enabled=False),
            watch=WatchConfig(poll_interval_ms=50),
        )

        rules = [
            RuleConfig(name="test_5xx", type="regex", pattern=r"\s5\d{2}\s", level="error", priority=10),
        ]

        matches = []

        def on_match(entry, matched_rules):
            matches.append((entry, matched_rules))

        monitor = RealtimeMonitor(
            db=db,
            settings=settings,
            parser=NginxParser(),
            rules=rules,
            on_match=on_match,
        )

        # Process a line that should NOT match
        line = '1.1.1.1 - - [10/Jun/2026:10:00:01 +0800] "GET /ok HTTP/1.1" 200 50 "-" "ua" 0.1'
        monitor._process_line(line)

        assert len(matches) == 0

    def test_counters(self, tmp_path):
        db = Database(tmp_path / "test.db")
        settings = Settings(
            database_path=str(tmp_path / "test.db"),
            batch_size=100,
            slow_request=SlowRequestThreshold(warning_ms=1000.0, critical_ms=5000.0),
            auth=AuthConfig(enabled=False),
            watch=WatchConfig(poll_interval_ms=50),
        )

        rules = [
            RuleConfig(name="test_5xx", type="regex", pattern=r"\s5\d{2}\s", level="error", priority=10),
        ]

        monitor = RealtimeMonitor(
            db=db, settings=settings, parser=NginxParser(), rules=rules,
        )

        lines = [
            '1.1.1.1 - - [10/Jun/2026:10:00:01 +0800] "GET / HTTP/1.1" 200 50 "-" "ua" 0.1',
            '1.1.1.1 - - [10/Jun/2026:10:00:02 +0800] "GET / HTTP/1.1" 500 50 "-" "ua" 0.1',
            '1.1.1.1 - - [10/Jun/2026:10:00:03 +0800] "GET / HTTP/1.1" 502 50 "-" "ua" 0.1',
        ]

        for line in lines:
            monitor._process_line(line)

        assert monitor._total_lines == 3
        assert monitor._matched_lines == 2
