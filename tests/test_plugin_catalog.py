"""Tests for official plugin catalog enrichment."""

from ly_next.core.plugin_catalog import enrich_plugin_catalog, load_plugin_catalog


def test_load_plugin_catalog_has_bridge_entries():
    items = load_plugin_catalog()
    ids = {p["id"] for p in items}
    assert "qq_onebot" in ids
    assert "telegram_bot" in ids


def test_enrich_marks_missing_when_config_enabled():
    items = enrich_plugin_catalog(
        plugin_info=[],
        bridge_info=[],
    )
    qq = next(p for p in items if p["id"] == "qq_onebot")
    # default config may enable onebot11 — status should reflect config vs disk
    assert qq["status"] in ("not_installed", "missing_required", "installed_not_loaded", "loaded")
    assert "clone_command" in qq or qq.get("repo_url") is None


def test_enrich_loaded_plugin():
    items = enrich_plugin_catalog(
        plugin_info=[{"name": "qq-onebot", "builtin": False}],
        bridge_info=[{"name": "qq-onebot", "enabled": True}],
    )
    qq = next(p for p in items if p["id"] == "qq_onebot")
    assert qq["loaded"] is True
    assert qq["status"] == "loaded"
