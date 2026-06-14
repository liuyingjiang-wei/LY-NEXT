"""Tests for plugin dependency discovery and manifest generation."""

from __future__ import annotations

from ly_next.core.plugin_deps import (
    _parse_requirements_text,
    discover_plugin_requirements,
    sync_plugin_dependencies,
    write_plugin_requirements_manifest,
)


def test_parse_requirements_skips_ly_next():
    lines = _parse_requirements_text(
        "ly-next\nLY-NEXT\naiohttp>=3.9\n# comment\npycryptodome>=3.20\n"
    )
    assert lines == ["aiohttp>=3.9", "pycryptodome>=3.20"]


def test_discover_plugin_requirements_from_local_dir(tmp_path, monkeypatch):
    plugin_root = tmp_path / "plugins" / "local" / "wechat_oc"
    plugin_root.mkdir(parents=True)
    (plugin_root / "requirements.txt").write_text(
        "ly-next\naiohttp>=3.9\npycryptodome>=3.20\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("ly_next.core.plugin_deps.get_project_root", lambda: tmp_path)
    monkeypatch.setattr("ly_next.core.plugin_deps.get_data_root", lambda: tmp_path / "data" / "ly_next")
    monkeypatch.setattr(
        "ly_next.core.plugin.loader._plugin_dir",
        lambda: tmp_path / "plugins",
    )
    monkeypatch.setattr(
        "ly_next.core.plugin.loader._plugin_extra_dirs",
        lambda: [tmp_path / "plugins" / "local"],
    )

    found = discover_plugin_requirements()
    assert len(found) == 1
    assert found[0]["plugin_dir"] == "plugins/local/wechat_oc"
    assert found[0]["requirements"] == ["aiohttp>=3.9", "pycryptodome>=3.20"]


def test_write_manifest_under_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr("ly_next.core.plugin_deps.get_project_root", lambda: tmp_path)
    monkeypatch.setattr("ly_next.core.plugin_deps.get_data_root", lambda: tmp_path / "data" / "ly_next")

    path = write_plugin_requirements_manifest(["aiohttp>=3.9"])
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "aiohttp>=3.9" in text
    assert "ly-next" not in text


def test_sync_plugin_dependencies_dry_run(tmp_path, monkeypatch):
    plugin_root = tmp_path / "plugins" / "local" / "demo"
    plugin_root.mkdir(parents=True)
    (plugin_root / "requirements.txt").write_text("httpx>=0.26\n", encoding="utf-8")

    monkeypatch.setattr("ly_next.core.plugin_deps.get_project_root", lambda: tmp_path)
    monkeypatch.setattr("ly_next.core.plugin_deps.get_data_root", lambda: tmp_path / "data" / "ly_next")
    monkeypatch.setattr(
        "ly_next.core.plugin.loader._plugin_dir",
        lambda: tmp_path / "plugins",
    )
    monkeypatch.setattr(
        "ly_next.core.plugin.loader._plugin_extra_dirs",
        lambda: [tmp_path / "plugins" / "local"],
    )

    result = sync_plugin_dependencies(install=False)
    assert result["ok"] is True
    assert result["requirements"] == ["httpx>=0.26"]


def test_sync_plugin_dependencies_uses_pip_when_uv_missing(tmp_path, monkeypatch):
    plugin_root = tmp_path / "plugins" / "local" / "demo"
    plugin_root.mkdir(parents=True)
    (plugin_root / "requirements.txt").write_text("httpx>=0.26\n", encoding="utf-8")

    monkeypatch.setattr("ly_next.core.plugin_deps.get_project_root", lambda: tmp_path)
    monkeypatch.setattr("ly_next.core.plugin_deps.get_data_root", lambda: tmp_path / "data" / "ly_next")
    monkeypatch.setattr(
        "ly_next.core.plugin.loader._plugin_dir",
        lambda: tmp_path / "plugins",
    )
    monkeypatch.setattr(
        "ly_next.core.plugin.loader._plugin_extra_dirs",
        lambda: [tmp_path / "plugins" / "local"],
    )
    monkeypatch.setattr("ly_next.core.plugin_deps.shutil.which", lambda _name: None)

    calls: list[list[str]] = []

    class FakeProc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return FakeProc()

    monkeypatch.setattr("ly_next.core.plugin_deps.subprocess.run", fake_run)

    result = sync_plugin_dependencies(install=True)
    assert result["installed"] == 1
    assert calls
    assert calls[0][1:3] == ["-m", "pip"]
