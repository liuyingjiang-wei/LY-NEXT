from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ly_next.agent import prompt_templates as pt

_BASE_PROMPTS: dict[str, Any] = {
    "enabled": True,
    "prompts_dir": "prompts",
    "native_system_file": "native_system.md",
    "compat_react_preamble_file": "compat_react_preamble.md",
    "plan_decision_preamble_file": "plan_decision_preamble.md",
    "tool_manifest_file": "tool_manifest_suffix.md",
}


def _patch_prompts(
    monkeypatch: pytest.MonkeyPatch,
    *,
    data_root: Path,
    builtin_dir: Path,
    pcfg: dict[str, Any],
) -> None:
    orig_get = pt.config.get

    def fake_get(key: str, default=None):
        if key == "agent.prompts":
            return pcfg
        return orig_get(key, default)

    monkeypatch.setattr(pt.config, "get", fake_get)
    monkeypatch.setattr(pt, "get_data_root", lambda: data_root)
    monkeypatch.setattr(pt, "_BUILTIN_DIR", builtin_dir)
    pt._CACHE.clear()


def test_build_compat_contains_protocol_and_dialog():
    s = pt.build_compat_decision_prompt(
        dialog="user says hi",
        tools=[{"name": "t1", "description": "d1"}],
        scratchpad="(empty)",
    )
    assert "You MUST output only JSON" in s
    assert "user says hi" in s
    assert "t1" in s


def test_format_tool_manifest_prefixes_newlines():
    b = pt.format_tool_manifest_block(["a", "b"])
    assert b.startswith("\n\n")
    assert "a, b" in b


def test_get_native_system_non_empty():
    assert len(pt.get_native_system_prefix()) > 20


def test_build_compat_skips_tools_without_name():
    s = pt.build_compat_decision_prompt(
        dialog="x",
        tools=[{"description": "orphan"}, {"name": "t1", "description": "d1"}],
        scratchpad="",
    )
    assert "t1" in s and "d1" in s
    assert "orphan" not in s


def test_prompts_disabled_reads_data_not_builtin(tmp_path, monkeypatch):
    data_root = tmp_path / "data_ly_next"
    pdir = data_root / "prompts"
    pdir.mkdir(parents=True)
    (pdir / "native_system.md").write_text("DATAONLY_MARKER\n", encoding="utf-8")

    fake_builtin = tmp_path / "builtin"
    fake_builtin.mkdir()
    (fake_builtin / "native_system.md").write_text("BUILTIN_SHOULD_NOT_APPEAR\n", encoding="utf-8")

    _patch_prompts(
        monkeypatch,
        data_root=data_root,
        builtin_dir=fake_builtin,
        pcfg={**_BASE_PROMPTS, "enabled": False},
    )
    text = pt.get_native_system_prefix()
    assert "DATAONLY_MARKER" in text
    assert "BUILTIN_SHOULD_NOT_APPEAR" not in text


def test_prompts_enabled_uses_builtin_when_no_data_file(tmp_path, monkeypatch):
    data_root = tmp_path / "data_ly_next"
    (data_root / "prompts").mkdir(parents=True)

    fake_builtin = tmp_path / "builtin"
    fake_builtin.mkdir()
    (fake_builtin / "native_system.md").write_text("BUILTIN_MARKER\n", encoding="utf-8")

    _patch_prompts(
        monkeypatch,
        data_root=data_root,
        builtin_dir=fake_builtin,
        pcfg={**_BASE_PROMPTS, "enabled": True},
    )
    assert "BUILTIN_MARKER" in pt.get_native_system_prefix()
