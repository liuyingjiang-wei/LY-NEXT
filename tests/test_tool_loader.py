from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from ly_next.tools.base import tool
from ly_next.tools.loader import register_tools_from_directory
from ly_next.tools.registry import ToolRegistry


@tool(name="echo_test", description="Echo input for tool loader tests", category="general")
async def echo_test(message: str = "") -> str:
    return message or "ok"


def test_register_tools_from_directory(tmp_path: Path):
    tool_file = tmp_path / "sample_tool.py"
    src = Path(__file__).resolve().parent / "fixtures" / "sample_tool_plugin.py"
    tool_file.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    registry = ToolRegistry()
    with (
        patch(
            "ly_next.tools.loader.plugin_security_profile",
            return_value="development",
        ),
        patch("ly_next.tools.loader._tool_plugin_dir", return_value=tmp_path),
    ):
        n = register_tools_from_directory(registry)
    assert n >= 1
    assert registry.has("sample_echo")
