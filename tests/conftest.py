from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path

import pytest

from ly_next.tools.base import BaseTool, ToolDefinition, ToolResult
from ly_next.tools.registry import ToolRegistry

_SESSION_BASE: Path | None = None
_PYTEST_TEMP_ROOT = Path(tempfile.gettempdir()) / "ly-next" / "pytest-sessions"


def pytest_configure(config: pytest.Config) -> None:
    """Avoid pytest's shared ``pytest-of-<user>`` dir (WinError 5 on Windows)."""
    global _SESSION_BASE
    stamp = int(time.time() * 1000) if sys.platform == "win32" else os.getpid()
    _SESSION_BASE = _PYTEST_TEMP_ROOT / f"run-{os.getpid()}-{stamp}"
    _SESSION_BASE.mkdir(parents=True, exist_ok=True)
    config.option.basetemp = str(_SESSION_BASE)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    del session, exitstatus
    if _SESSION_BASE is None:
        return
    with suppress(OSError, PermissionError):
        shutil.rmtree(_SESSION_BASE, ignore_errors=True)


class FakeTool(BaseTool):
    def __init__(self, name: str, category: str = "general") -> None:
        self._definition = ToolDefinition(
            name=name,
            description="test",
            parameters={"type": "object", "properties": {}},
            category=category,
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def execute(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, result=None)


@pytest.fixture
def fake_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(FakeTool("calculator", "safe"))
    reg.register(FakeTool("http_fetch", "network"))
    reg.register(FakeTool("web_search", "network"))
    reg.register(FakeTool("mcp_search", "mcp"))
    return reg
