"""规则引擎测试"""

from log_inspector.config import RuleConfig
from log_inspector.parsers.base import LogEntry
from log_inspector.rules.engine import RuleEngine


class TestRuleEngine:
    def test_regex_rule_matches(self):
        rules = [RuleConfig(name="r1", type="regex", pattern=r"500", level="error", priority=10)]
        engine = RuleEngine(rules)
        entry = LogEntry(message="HTTP 500 Internal Server Error", raw_line="... 500 ...")
        matched = engine.match(entry)
        assert len(matched) == 1
        assert matched[0].name == "r1"

    def test_regex_rule_no_match(self):
        rules = [RuleConfig(name="r1", type="regex", pattern=r"500", level="error", priority=10)]
        engine = RuleEngine(rules)
        entry = LogEntry(message="HTTP 200 OK", raw_line="... 200 ...")
        matched = engine.match(entry)
        assert len(matched) == 0

    def test_threshold_rule(self):
        rules = [RuleConfig(name="slow", type="threshold", threshold=1000.0, level="warning", priority=8)]
        engine = RuleEngine(rules)

        fast_entry = LogEntry(message="fast", raw_line="", metadata={"response_time_ms": 500.0})
        assert engine.match(fast_entry) == []

        slow_entry = LogEntry(message="slow", raw_line="", metadata={"response_time_ms": 1500.0})
        matched = engine.match(slow_entry)
        assert len(matched) == 1

    def test_keyword_rule(self):
        rules = [RuleConfig(name="kw", type="keyword", pattern="timeout,error", level="error", priority=9)]
        engine = RuleEngine(rules)

        entry = LogEntry(message="Connection timeout occurred", raw_line="timeout")
        matched = engine.match(entry)
        assert len(matched) == 1

    def test_disabled_rule_skipped(self):
        rules = [RuleConfig(name="r1", type="regex", pattern="error", level="error", priority=10, enabled=False)]
        engine = RuleEngine(rules)
        entry = LogEntry(message="error happened", raw_line="error")
        assert engine.match(entry) == []

    def test_ignore_action_blocks_all(self):
        rules = [
            RuleConfig(name="ignore", type="regex", pattern="health", level="info", priority=100, action="ignore"),
            RuleConfig(name="error", type="regex", pattern="health", level="error", priority=1, action="alert"),
        ]
        engine = RuleEngine(rules)
        entry = LogEntry(message="GET /health 200", raw_line="GET /health 200")
        matched = engine.match(entry)
        assert matched == []

    def test_conflict_detection_same_pattern_diff_action(self):
        rules = [
            RuleConfig(name="alert_5xx", type="regex", pattern=r"5\d{2}", level="error", priority=10, action="alert"),
            RuleConfig(name="ignore_5xx", type="regex", pattern=r"5\d{2}", level="error", priority=5, action="ignore"),
        ]
        engine = RuleEngine(rules)
        assert len(engine.conflicts) == 1

    def test_no_conflict_different_scope(self):
        rules = [
            RuleConfig(name="r1", type="regex", pattern="error", priority=10, scope="/api/*", action="alert"),
            RuleConfig(name="r2", type="regex", pattern="error", priority=5, scope="/admin/*", action="ignore"),
        ]
        engine = RuleEngine(rules)
        assert len(engine.conflicts) == 0

    def test_priority_ordering(self):
        rules = [
            RuleConfig(name="low", type="keyword", pattern="error", level="warning", priority=1),
            RuleConfig(name="high", type="keyword", pattern="error", level="error", priority=10),
        ]
        engine = RuleEngine(rules)
        entry = LogEntry(message="error happened", raw_line="error")
        matched = engine.match(entry)
        assert matched[0].name == "high"

    def test_filter_by_rule_names(self):
        rules = [
            RuleConfig(name="r1", type="keyword", pattern="error", level="error", priority=10),
            RuleConfig(name="r2", type="keyword", pattern="error", level="warning", priority=5),
        ]
        engine = RuleEngine(rules)
        entry = LogEntry(message="error", raw_line="error")
        matched = engine.match(entry, rule_names=["r2"])
        assert len(matched) == 1
        assert matched[0].name == "r2"
