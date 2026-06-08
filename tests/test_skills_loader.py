from __future__ import annotations

from pathlib import Path

import pytest

from ly_next.agent import skills_loader as sl


@pytest.fixture(autouse=True)
def reset_skills_cache():
    sl.invalidate_skills_cache()
    yield
    sl.invalidate_skills_cache()


def test_parse_frontmatter_without_yaml():
    text = "# Title\n\nShort description line.\n\nMore body."
    name, desc = sl._parse_frontmatter(text)
    assert name == ""
    assert desc == "Short description line."
    assert len(desc) < len(text)


def test_discover_skill_with_frontmatter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    skills_dir = tmp_path / "skills" / "demo-skill"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text(
        "---\nname: Demo Skill\ndescription: Does demo things.\n---\n\n# Body\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sl, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(
        sl,
        "_skills_cfg",
        lambda: {"enabled": True, "dirs": ["skills"], "cache_ttl_seconds": 0},
    )

    items = sl.discover_skills(force=True)
    assert len(items) == 1
    assert items[0].id == "demo-skill"
    assert items[0].name == "Demo Skill"
    assert "demo things" in items[0].description

    text, err = sl.read_skill_content("demo-skill")
    assert err is None
    assert "Body" in (text or "")


@pytest.mark.asyncio
async def test_list_skills_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from ly_next.tools.skills_tools import list_skills, read_skill

    skills_dir = tmp_path / ".agents" / "skills" / "foo"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text("# Foo\n\nRun foo workflow.\n", encoding="utf-8")
    monkeypatch.setattr(sl, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(
        sl,
        "_skills_cfg",
        lambda: {"enabled": True, "dirs": [".agents/skills"], "cache_ttl_seconds": 0},
    )

    out = await list_skills()
    assert out.success
    assert out.result["count"] == 1

    body = await read_skill(skill_id="foo")
    assert body.success
    assert "Foo" in body.result["content"]
