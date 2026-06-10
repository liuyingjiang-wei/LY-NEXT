from __future__ import annotations

from pathlib import Path

import pytest

from ly_next.tools.host_files import read_file_range
from ly_next.tools.host_search import grep_code


@pytest.mark.asyncio
async def test_grep_code_finds_pattern(tmp_path: Path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(
        "ly_next.tools.host_sandbox.config.get",
        lambda key, default=None: (
            [str(root)]
            if key == "tools.host.roots"
            else True
            if key == "tools.host.enabled"
            else default
        ),
    )
    result = await grep_code(pattern=r"def hello", path=str(root / "a.py"))
    assert result.success is True
    assert len(result.result["matches"]) == 1


@pytest.mark.asyncio
async def test_read_file_range_lines(tmp_path: Path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    fp = root / "a.txt"
    fp.write_text("line1\nline2\nline3\n", encoding="utf-8")
    monkeypatch.setattr(
        "ly_next.tools.host_sandbox.config.get",
        lambda key, default=None: (
            [str(root)]
            if key == "tools.host.roots"
            else True
            if key == "tools.host.enabled"
            else default
        ),
    )
    result = await read_file_range(path=str(fp), start_line=2, end_line=2)
    assert result.success is True
    assert "2:line2" in result.result["content"]
