"""配置校验测试"""

import pytest
from pathlib import Path

from log_inspector.config import (
    load_yaml,
    validate_config,
    try_load_yaml,
    try_validate_config,
    Settings,
    RulesFile,
    RuleConfig,
)


class TestYamlLoading:
    def test_load_valid_yaml(self, tmp_path):
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("key: value\nlist:\n  - a\n  - b\n", encoding="utf-8")
        data = load_yaml(yaml_file)
        assert data["key"] == "value"
        assert data["list"] == ["a", "b"]

    def test_load_empty_yaml(self, tmp_path):
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("", encoding="utf-8")
        data = load_yaml(yaml_file)
        assert data == {}

    def test_load_nonexistent_yaml(self, tmp_path):
        with pytest.raises(SystemExit):
            load_yaml(tmp_path / "noexist.yaml")

    def test_load_invalid_yaml(self, tmp_path):
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("key: [invalid\n  broken", encoding="utf-8")
        with pytest.raises(SystemExit):
            load_yaml(yaml_file)


class TestConfigValidation:
    def test_valid_settings(self):
        data = {
            "database_path": "test.db",
            "export_dir": "exports",
            "batch_size": 5000,
        }
        result = validate_config(data, Settings, "test")
        assert result.database_path == "test.db"
        assert result.batch_size == 5000

    def test_default_settings(self):
        result = validate_config({}, Settings, "test")
        assert result.batch_size == 10000
        assert result.database_path == "data/log_inspector.db"

    def test_invalid_settings_type(self):
        data = {"batch_size": "not_a_number"}
        with pytest.raises(SystemExit):
            validate_config(data, Settings, "test")

    def test_valid_rules(self):
        data = {
            "rules": [
                {"name": "test", "type": "regex", "pattern": "error", "level": "error"}
            ]
        }
        result = validate_config(data, RulesFile, "test")
        assert len(result.rules) == 1
        assert result.rules[0].name == "test"

    def test_invalid_rule_missing_name(self):
        data = {"rules": [{"type": "regex"}]}
        with pytest.raises(SystemExit):
            validate_config(data, RulesFile, "test")


class TestTryLoadYaml:
    """非中断式 YAML 加载（供 config check 使用）"""

    def test_valid_file(self, tmp_path):
        f = tmp_path / "ok.yaml"
        f.write_text("key: value\n", encoding="utf-8")
        data, errors = try_load_yaml(f)
        assert data == {"key": "value"}
        assert errors == []

    def test_nonexistent_file(self, tmp_path):
        data, errors = try_load_yaml(tmp_path / "no.yaml")
        assert data is None
        assert len(errors) == 1
        assert "不存在" in errors[0]

    def test_syntax_error_reports_location(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("items:\n  - valid\n  - [broken\n  unclosed", encoding="utf-8")
        data, errors = try_load_yaml(f)
        assert data is None
        assert len(errors) == 1
        assert "行" in errors[0]
        assert "原因" in errors[0]

    def test_empty_file_returns_empty_dict(self, tmp_path):
        f = tmp_path / "empty.yaml"
        f.write_text("", encoding="utf-8")
        data, errors = try_load_yaml(f)
        assert data == {}
        assert errors == []


class TestTryValidateConfig:
    """非中断式 Pydantic 校验"""

    def test_valid_data(self):
        result, errors = try_validate_config({"batch_size": 500}, Settings)
        assert result is not None
        assert errors == []
        assert result.batch_size == 500

    def test_invalid_type_reports_field(self):
        result, errors = try_validate_config({"batch_size": "oops"}, Settings)
        assert result is None
        assert len(errors) >= 1
        assert "batch_size" in errors[0]
        assert "oops" in errors[0]

    def test_multiple_errors_all_reported(self):
        data = {"rules": [{"type": 123}, {"name": "ok", "type": "regex"}]}
        result, errors = try_validate_config(data, RulesFile)
        assert result is None
        assert len(errors) >= 1

    def test_continues_after_first_error(self):
        """即使第一个字段有问题，后续字段也被检查"""
        data = {"batch_size": "bad", "export_dir": 12345}
        result, errors = try_validate_config(data, Settings)
        assert result is None
        assert len(errors) >= 2


class TestConfigCheckCommand:
    """config check 命令的端到端测试"""

    def test_all_valid(self, tmp_path):
        (tmp_path / "settings.yaml").write_text("batch_size: 5000\n", encoding="utf-8")
        (tmp_path / "rules.yaml").write_text("rules: []\n", encoding="utf-8")
        (tmp_path / "tasks.yaml").write_text("tasks: []\n", encoding="utf-8")

        from typer.testing import CliRunner
        from log_inspector.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["config", "check", "--config-dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "settings.yaml" in result.output
        assert "rules.yaml" in result.output
        assert "tasks.yaml" in result.output

    def test_one_broken_still_checks_others(self, tmp_path):
        """第一个文件有语法错误，不会中断后续文件的检查"""
        (tmp_path / "settings.yaml").write_text("broken: [unclosed\n", encoding="utf-8")
        (tmp_path / "rules.yaml").write_text("rules: []\n", encoding="utf-8")
        (tmp_path / "tasks.yaml").write_text("tasks: []\n", encoding="utf-8")

        from typer.testing import CliRunner
        from log_inspector.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["config", "check", "--config-dir", str(tmp_path)])
        assert result.exit_code == 1
        # settings 报错
        assert "settings.yaml" in result.output
        # rules 和 tasks 仍然被检查通过
        assert "rules.yaml" in result.output
        assert "tasks.yaml" in result.output

    def test_validation_error_shows_reason(self, tmp_path):
        """字段类型错误时给出字段名和原因"""
        (tmp_path / "settings.yaml").write_text("batch_size: not_a_number\n", encoding="utf-8")
        (tmp_path / "rules.yaml").write_text("rules: []\n", encoding="utf-8")
        (tmp_path / "tasks.yaml").write_text("tasks: []\n", encoding="utf-8")

        from typer.testing import CliRunner
        from log_inspector.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["config", "check", "--config-dir", str(tmp_path)])
        assert result.exit_code == 1
        assert "batch_size" in result.output
        assert "not_a_number" in result.output

    def test_yaml_syntax_error_shows_line(self, tmp_path):
        """YAML 语法错误时给出行号"""
        bad_yaml = "rules:\n  - name: ok\n  - [broken_bracket\n"
        (tmp_path / "settings.yaml").write_text("{}\n", encoding="utf-8")
        (tmp_path / "rules.yaml").write_text(bad_yaml, encoding="utf-8")
        (tmp_path / "tasks.yaml").write_text("tasks: []\n", encoding="utf-8")

        from typer.testing import CliRunner
        from log_inspector.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["config", "check", "--config-dir", str(tmp_path)])
        assert result.exit_code == 1
        assert "行" in result.output
