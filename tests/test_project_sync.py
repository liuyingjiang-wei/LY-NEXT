"""Tests for project sync wrapper."""

from __future__ import annotations

from ly_next.core.project_sync import run_project_sync


def test_run_project_sync_calls_inexact_uv_sync(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("ly_next.core.project_sync.get_project_root", lambda: tmp_path)
    monkeypatch.setattr("ly_next.core.project_sync.shutil.which", lambda _: "uv")
    monkeypatch.setattr("ly_next.core.project_sync.subprocess.run", fake_run)
    monkeypatch.setattr(
        "ly_next.core.plugin_deps.sync_plugin_dependencies",
        lambda **kwargs: {"ok": True, "message": "plugin ok"},
    )

    result = run_project_sync()
    assert calls[0][:3] == ["uv", "sync", "--inexact"]
    assert result["ok"] is True
    assert "inexact" in result["message"]
