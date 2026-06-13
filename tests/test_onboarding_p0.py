"""Tests for config presets and onboarding helpers."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ly_next.core.config_presets import apply_config_preset, list_config_presets
from ly_next.core.onboarding_helpers import (
    gather_auth_key_status,
    login_page_hints,
    sync_auth_first_run_file,
)
from ly_next.main import create_app


def _api_headers():
    from ly_next.core.config import config

    key = str(config.get("auth.api_key") or "test-key")
    return {"X-API-Key": key}


def test_list_config_presets():
    presets = list_config_presets()
    ids = {p["id"] for p in presets}
    assert ids == {"minimal", "standard", "full_stack"}
    assert all(p.get("label") and p.get("description") for p in presets)


def test_apply_config_preset_minimal(monkeypatch, tmp_path):
    stored: dict = {"agent": {"reasoning_mode": "react", "persistence": {"enabled": True}}}

    def fake_get(key, default=None):
        if key == "agent":
            return stored.get("agent", default)
        if key == "auth.api_key":
            return "test-key"
        return default

    def fake_set(key, val, save=True):
        stored[key] = val

    monkeypatch.setattr("ly_next.core.config_presets.config.get", fake_get)
    monkeypatch.setattr("ly_next.core.config_presets.config.set", fake_set)
    monkeypatch.setattr("ly_next.core.config_presets.config.save", lambda: None)
    monkeypatch.setattr("ly_next.core.config_presets.config.load", lambda: None)
    monkeypatch.setattr(
        "ly_next.core.system_readiness.invalidate_readiness_cache",
        lambda: None,
    )

    result = apply_config_preset("minimal")
    assert result["ok"] is True
    assert result["preset_id"] == "minimal"
    assert stored["agent"]["reasoning_mode"] == "chat"
    assert stored["agent"]["persistence"]["enabled"] is False


def test_apply_config_preset_unknown():
    with pytest.raises(ValueError, match="未知预设"):
        apply_config_preset("nope")


def test_gather_auth_key_status_no_key(monkeypatch):
    monkeypatch.setattr(
        "ly_next.core.onboarding_helpers.config.get",
        lambda key, default=None: "" if key == "auth.api_key" else default,
    )
    monkeypatch.setattr(
        "ly_next.core.onboarding_helpers.read_first_run_api_key",
        lambda: None,
    )
    monkeypatch.setattr(
        "ly_next.core.onboarding_helpers.first_run_notice_path",
        lambda: __import__("pathlib").Path("/tmp/nope/FIRST_RUN.txt"),
    )
    status = gather_auth_key_status()
    assert status["configured"] is False
    assert "未设置" in (status["hint"] or "")


def test_sync_auth_first_run_file(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "ly_next.core.onboarding_helpers.config.get",
        lambda key, default=None: "sync-key" if key == "auth.api_key" else default,
    )
    path = tmp_path / "FIRST_RUN.txt"
    monkeypatch.setattr(
        "ly_next.core.onboarding_helpers.first_run_notice_path",
        lambda: path,
    )
    monkeypatch.setattr(
        "ly_next.core.onboarding_helpers.get_data_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "ly_next.core.onboarding_helpers.read_first_run_api_key",
        lambda: "sync-key" if path.is_file() else None,
    )

    def _sync(key):
        path.write_text(f"API Key: {key}\n", encoding="utf-8")
        return True

    monkeypatch.setattr("ly_next.core.onboarding_helpers.sync_first_run_notice", _sync)
    out = sync_auth_first_run_file()
    assert out["ok"] is True
    assert path.is_file()


def test_login_page_hints_safe(monkeypatch):
    monkeypatch.setattr(
        "ly_next.core.onboarding_helpers.gather_auth_key_status",
        lambda: {
            "configured": True,
            "masked_key": "abcd…wxyz",
            "first_run_path": "data/ly_next/FIRST_RUN.txt",
            "first_run_exists": True,
            "synced": True,
            "hint": "ok",
        },
    )
    hints = login_page_hints()
    assert hints["masked_key"] == "abcd…wxyz"
    assert "docs_url" in hints


def test_config_presets_api():
    client = TestClient(create_app())
    r = client.get("/api/system/config/presets", headers=_api_headers())
    assert r.status_code == 200
    presets = r.json()["presets"]
    assert len(presets) == 3


def test_auth_key_status_api():
    client = TestClient(create_app())
    r = client.get("/api/system/auth/key-status", headers=_api_headers())
    assert r.status_code == 200
    data = r.json()
    assert "configured" in data
    assert "masked_key" in data
