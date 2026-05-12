from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ly_next.tools.memory_note import remember_fact


@pytest.mark.asyncio
async def test_remember_fact_appends_under_project(tmp_path: Path) -> None:
    mem = tmp_path / "MEMORY.md"
    cfg = MagicMock()

    def get(key: str, default=None):
        if key == "agent.memory.enabled":
            return True
        if key == "agent.memory.path":
            return "MEMORY.md"
        return default

    cfg.get = get
    with (
        patch("ly_next.tools.memory_note.config", cfg),
        patch("ly_next.tools.memory_note.get_project_root", return_value=tmp_path),
    ):
        r = await remember_fact.execute(note="用户偏好深色主题")
    assert r.success is True
    assert mem.is_file()
    text = mem.read_text(encoding="utf-8")
    assert "用户偏好深色主题" in text


@pytest.mark.asyncio
async def test_remember_fact_rejects_path_outside_project(tmp_path: Path) -> None:
    outside = Path(tmp_path) / ".." / "outside_mem.md"
    cfg = MagicMock()

    def get(key: str, default=None):
        if key == "agent.memory.enabled":
            return True
        if key == "agent.memory.path":
            return str(outside.resolve())
        return default

    cfg.get = get
    with (
        patch("ly_next.tools.memory_note.config", cfg),
        patch("ly_next.tools.memory_note.get_project_root", return_value=tmp_path),
    ):
        r = await remember_fact.execute(note="x")
    assert r.success is False
    assert r.error
