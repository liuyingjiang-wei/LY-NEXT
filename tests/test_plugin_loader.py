from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from ly_next.core.app_context import AppContext
from ly_next.core.plugin import PluginLoader
from ly_next.core.plugin.builtin_plugin import BuiltinPlugin
from ly_next.core.plugin.loader import _extract_plugin_from_module
from ly_next.core.plugin.protocol import LyNextPlugin
from ly_next.tools.registry import ToolRegistry


class _EchoPlugin(LyNextPlugin):
    name = "test-echo"
    version = "0.0.1"


def test_builtin_plugin_registers_tools_and_agents():
    registry = ToolRegistry()
    ctx = AppContext(
        config=__import__("ly_next.core.config", fromlist=["config"]).config, tool_registry=registry
    )
    BuiltinPlugin().register_tools(registry, ctx)
    assert len(registry) > 0
    assert ctx.extras.get("builtin_tools_registered", 0) > 0


def test_plugin_loader_includes_builtin():
    ctx = AppContext.create()
    reg = PluginLoader().load_all(ctx, include_builtin=True)
    names = [p.name for p in reg.list_plugins()]
    assert "ly-next-builtin" in names
    assert "ly-next-tool-directory" in names
    assert "ly-next-directory-api" in names
    assert "ly-next-bridges" in names


def test_extract_plugin_from_module_variants():
    import types

    mod = types.ModuleType("m")
    mod.plugin = _EchoPlugin()
    assert _extract_plugin_from_module(mod) is mod.plugin

    mod2 = types.ModuleType("m2")

    class P(LyNextPlugin):
        name = "cls-plugin"

    mod2.Plugin = P
    got = _extract_plugin_from_module(mod2)
    assert got is not None
    assert got.name == "cls-plugin"


def test_load_directory_plugin(tmp_path: Path):
    plugin_file = tmp_path / "hello_plugin.py"
    plugin_file.write_text(
        "from ly_next.core.plugin.protocol import LyNextPlugin\n"
        "class HelloPlugin(LyNextPlugin):\n"
        "    name = 'hello-from-dir'\n"
        "plugin = HelloPlugin()\n",
        encoding="utf-8",
    )

    ctx = AppContext.create()
    with (
        patch(
            "ly_next.core.plugin.loader.plugin_security_profile",
            return_value="development",
        ),
        patch("ly_next.core.plugin.loader._plugin_dir", return_value=tmp_path),
    ):
        reg = PluginLoader().load_all(ctx, include_builtin=False)
    assert any(p.name == "hello-from-dir" for p in reg.list_plugins())


def test_production_profile_skips_directory_plugins(tmp_path: Path):
    (tmp_path / "x.py").write_text("plugin = None\n", encoding="utf-8")
    ctx = AppContext.create()
    with (
        patch(
            "ly_next.core.plugin.loader.plugin_security_profile",
            return_value="production",
        ),
        patch("ly_next.core.plugin.loader._plugin_dir", return_value=tmp_path),
    ):
        reg = PluginLoader().load_all(ctx, include_builtin=True)
    assert len(reg.list_plugins()) == 4
    assert reg.list_plugins()[0].name == "ly-next-builtin"
