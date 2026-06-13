"""Tests for plugin catalog enrichment and git clone helpers."""

from ly_next.core.plugin_catalog import (
    apply_mirror_to_url,
    build_git_clone_command,
    default_clone_path,
    derive_clone_subdir,
    enrich_git_clone_settings,
    enrich_plugin_catalog,
    get_git_clone_settings,
    load_plugin_catalog,
    resolve_plugin_repo_url,
    resolve_repo_url,
)


def test_load_plugin_catalog_has_known_plugins():
    items = load_plugin_catalog()
    ids = {p["id"] for p in items}
    assert "qq_onebot" in ids
    assert "telegram_bot" in ids
    qq = next(p for p in items if p["id"] == "qq_onebot")
    assert "repo_url" not in qq


def test_enrich_marks_missing_when_config_enabled():
    items = enrich_plugin_catalog(
        plugin_info=[],
        bridge_info=[],
    )
    qq = next(p for p in items if p["id"] == "qq_onebot")
    assert qq["status"] in (
        "not_installed",
        "missing_required",
        "installed_not_loaded",
        "loaded",
    )
    assert qq.get("needs_repo_url") is False
    assert qq.get("clone_command") is None


def test_enrich_loaded_plugin():
    items = enrich_plugin_catalog(
        plugin_info=[{"name": "qq-onebot", "builtin": False}],
        bridge_info=[{"name": "qq-onebot", "enabled": True}],
    )
    qq = next(p for p in items if p["id"] == "qq_onebot")
    assert qq["loaded"] is True
    assert qq["status"] == "loaded"


def test_apply_mirror_to_github_url(monkeypatch):
    monkeypatch.setattr(
        "ly_next.core.plugin_catalog.config",
        type(
            "C",
            (),
            {
                "get": staticmethod(
                    lambda key, default=None: {
                        "plugins.git_clone": {
                            "proxy_mode": "mirror",
                            "mirror_prefix": "https://gh-proxy.com/",
                            "mirror_hosts": ["github.com"],
                            "repo_url": "",
                            "repos": {},
                        }
                    }.get(key, default)
                )
            },
        )(),
    )
    url = "https://github.com/acme/qq-onebot.git"
    assert apply_mirror_to_url(url) == "https://gh-proxy.com/https://github.com/acme/qq-onebot.git"


def test_build_clone_command_with_local_proxy(monkeypatch):
    monkeypatch.setattr(
        "ly_next.core.plugin_catalog.config",
        type(
            "C",
            (),
            {
                "get": staticmethod(
                    lambda key, default=None: {
                        "plugins.git_clone": {
                            "proxy_mode": "local",
                            "http_proxy": "http://127.0.0.1:7890",
                            "https_proxy": "http://127.0.0.1:7890",
                            "mirror_prefix": "",
                            "repo_url": "https://github.com/acme/qq.git",
                            "repos": {},
                        }
                    }.get(key, default)
                )
            },
        )(),
    )
    cmd = build_git_clone_command(
        "https://github.com/acme/qq.git",
        "plugins/local/qq_onebot",
    )
    assert cmd is not None
    assert "http.proxy=http://127.0.0.1:7890" in cmd
    assert "clone https://github.com/acme/qq.git plugins/local/qq_onebot" in cmd


def test_resolve_repo_url_from_config(monkeypatch):
    monkeypatch.setattr(
        "ly_next.core.plugin_catalog.config",
        type(
            "C",
            (),
            {
                "get": staticmethod(
                    lambda key, default=None: {
                        "plugins.git_clone": {
                            "proxy_mode": "none",
                            "repo_url": "https://git.example.com/plugin.git",
                            "repos": {},
                        }
                    }.get(key, default)
                )
            },
        )(),
    )
    assert resolve_repo_url() == "https://git.example.com/plugin.git"
    assert resolve_plugin_repo_url("telegram_bot") == "https://git.example.com/plugin.git"
    assert get_git_clone_settings()["repo_url"] == "https://git.example.com/plugin.git"


def test_legacy_repos_fallback(monkeypatch):
    monkeypatch.setattr(
        "ly_next.core.plugin_catalog.config",
        type(
            "C",
            (),
            {
                "get": staticmethod(
                    lambda key, default=None: {
                        "plugins.git_clone": {
                            "proxy_mode": "none",
                            "repo_url": "",
                            "repos": {"telegram_bot": "https://git.example.com/legacy.git"},
                        }
                    }.get(key, default)
                )
            },
        )(),
    )
    assert resolve_repo_url() == "https://git.example.com/legacy.git"


def test_derive_clone_path_from_url():
    assert derive_clone_subdir("https://github.com/acme/my-plugin.git") == "my-plugin"
    assert default_clone_path("https://github.com/acme/my-plugin.git") == "plugins/local/my-plugin"


def test_enrich_git_clone_settings_command(monkeypatch):
    monkeypatch.setattr(
        "ly_next.core.plugin_catalog.config",
        type(
            "C",
            (),
            {
                "get": staticmethod(
                    lambda key, default=None: {
                        "plugins.git_clone": {
                            "proxy_mode": "none",
                            "repo_url": "https://github.com/acme/demo.git",
                        }
                    }.get(key, default)
                )
            },
        )(),
    )
    enriched = enrich_git_clone_settings()
    assert enriched["clone_path"] == "plugins/local/demo"
    assert enriched["clone_command"] is not None
    assert "plugins/local/demo" in enriched["clone_command"]
