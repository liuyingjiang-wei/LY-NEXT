from __future__ import annotations

from pathlib import Path

from ly_next.core.data_bootstrap import bootstrap_data_assets


def test_bootstrap_creates_prompts_and_knowledge(tmp_path: Path):
    root = tmp_path / "data_ly_next"
    created = bootstrap_data_assets(root)
    assert created["prompts"] >= 4
    assert created["knowledge"] >= 1
    assert (root / "prompts" / "native_system.md").is_file()
    assert (root / "knowledge" / "RAG_README.md").is_file()


def test_bootstrap_does_not_overwrite_existing(tmp_path: Path):
    root = tmp_path / "data_ly_next"
    pdir = root / "prompts"
    pdir.mkdir(parents=True)
    custom = pdir / "native_system.md"
    custom.write_text("USER_CUSTOM\n", encoding="utf-8")

    first = bootstrap_data_assets(root)
    assert first["prompts"] >= 0

    second = bootstrap_data_assets(root)
    assert second["prompts"] == 0
    assert custom.read_text(encoding="utf-8") == "USER_CUSTOM\n"


def test_bootstrap_respects_custom_prompts_subdir(tmp_path: Path):
    root = tmp_path / "data_ly_next"
    created = bootstrap_data_assets(root, prompts_subdir="my_prompts")
    assert created["prompts"] >= 1
    assert (root / "my_prompts" / "native_system.md").is_file()
