"""插件加载器 - 支持自定义解析器插件"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from rich.console import Console

from log_inspector.parsers.base import BaseParser

console = Console(stderr=True)


class PluginLoader:
    def __init__(self, plugin_dir: str = "plugins"):
        self.plugin_dir = Path(plugin_dir)
        self._parsers: list[BaseParser] = []

    def load_all(self) -> list[BaseParser]:
        """加载所有插件目录中的解析器"""
        if not self.plugin_dir.exists():
            return []

        for py_file in self.plugin_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            parser = self._load_plugin(py_file)
            if parser:
                self._parsers.append(parser)

        if self._parsers:
            console.print(
                f"[green]已加载 {len(self._parsers)} 个插件解析器: "
                f"{', '.join(p.name for p in self._parsers)}[/green]"
            )
        return self._parsers

    def _load_plugin(self, path: Path) -> BaseParser | None:
        """动态加载单个插件文件"""
        module_name = f"plugin_{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # 查找 BaseParser 子类
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseParser)
                    and attr is not BaseParser
                ):
                    instance = attr()
                    console.print(f"  [dim]加载插件: {instance.name} ({path.name})[/dim]")
                    return instance

        except Exception as e:
            console.print(f"[red]插件加载失败 {path.name}: {e}[/red]")
        return None

    def list_plugins(self) -> list[dict[str, str]]:
        """列出已加载的插件信息"""
        return [
            {"name": p.name, "description": p.description}
            for p in self._parsers
        ]
