"""Plugin catalog — install hints, git clone helpers, doctor/workbench integration."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ly_next.core.config import config, get_project_root
from ly_next.core.plugin.loader import directory_plugin_load_status

_CATALOG_PATH = get_project_root() / "plugins" / "catalog.json"

_PROXY_MODES = frozenset({"none", "local", "mirror", "both"})
_DEFAULT_MIRROR_HOSTS = ("github.com", "raw.githubusercontent.com")


def _catalog_path() -> Path:
    return _CATALOG_PATH


def load_plugin_catalog() -> list[dict[str, Any]]:
    path = _catalog_path()
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = raw.get("plugins") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict) and item.get("id"):
            out.append(dict(item))
    return out


def get_git_clone_settings() -> dict[str, Any]:
    """Normalized plugins.git_clone from config."""
    raw = config.get("plugins.git_clone")
    if not isinstance(raw, dict):
        raw = {}
    mode = str(raw.get("proxy_mode") or "none").strip().lower()
    if mode not in _PROXY_MODES:
        mode = "none"
    http_proxy = str(raw.get("http_proxy") or "").strip()
    https_proxy = str(raw.get("https_proxy") or "").strip() or http_proxy
    mirror_prefix = str(raw.get("mirror_prefix") or "").strip()
    hosts = raw.get("mirror_hosts")
    if not isinstance(hosts, list) or not hosts:
        hosts = list(_DEFAULT_MIRROR_HOSTS)
    else:
        hosts = [str(h).strip() for h in hosts if str(h).strip()]
    repos = raw.get("repos")
    if not isinstance(repos, dict):
        repos = {}
    repo_map = {str(k): str(v or "").strip() for k, v in repos.items()}
    repo_url = str(raw.get("repo_url") or "").strip()
    if not repo_url:
        for value in repo_map.values():
            if value:
                repo_url = value
                break
    return {
        "proxy_mode": mode,
        "http_proxy": http_proxy,
        "https_proxy": https_proxy,
        "mirror_prefix": mirror_prefix,
        "mirror_hosts": hosts,
        "repo_url": repo_url,
        "repos": repo_map,
    }


def derive_clone_subdir(repo_url: str) -> str:
    """Folder name under plugins/local/ inferred from Git URL."""
    src = str(repo_url or "").strip()
    if not src:
        return "plugin"
    try:
        path = (urlparse(src).path or "").strip("/")
    except ValueError:
        path = ""
    name = path.rsplit("/", 1)[-1] if path else "plugin"
    if name.lower().endswith(".git"):
        name = name[:-4]
    name = re.sub(r"[^\w.-]", "_", name).strip("._-")[:64]
    return name or "plugin"


def default_clone_path(repo_url: str) -> str:
    return f"plugins/local/{derive_clone_subdir(repo_url)}"


def resolve_repo_url() -> str:
    return str(get_git_clone_settings().get("repo_url") or "").strip()


def enrich_git_clone_settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = dict(settings or get_git_clone_settings())
    url = str(cfg.get("repo_url") or "").strip()
    clone_path = default_clone_path(url) if url else ""
    clone_cmd = build_git_clone_command(url, clone_path, cfg) if url else None
    cfg["clone_path"] = clone_path or None
    cfg["clone_command"] = clone_cmd
    return cfg


def resolve_plugin_repo_url(plugin_id: str) -> str:
    """Legacy per-plugin map; prefer plugins.git_clone.repo_url."""
    _ = plugin_id
    return resolve_repo_url()


def _host_matches_mirror(url: str, hosts: list[str]) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    for pattern in hosts:
        p = pattern.lower().strip()
        if not p:
            continue
        if host == p or host.endswith(f".{p}"):
            return True
    return False


def apply_mirror_to_url(url: str, settings: dict[str, Any] | None = None) -> str:
    """Prepend mirror_prefix for configured hosts (e.g. gh-proxy for GitHub)."""
    src = str(url or "").strip()
    if not src:
        return ""
    cfg = settings or get_git_clone_settings()
    mode = str(cfg.get("proxy_mode") or "none")
    if mode not in ("mirror", "both"):
        return src
    prefix = str(cfg.get("mirror_prefix") or "").strip()
    if not prefix:
        return src
    hosts = cfg.get("mirror_hosts") or list(_DEFAULT_MIRROR_HOSTS)
    if not _host_matches_mirror(src, hosts):
        return src
    if not prefix.endswith("/"):
        prefix = f"{prefix}/"
    if src.startswith("http://") or src.startswith("https://"):
        return f"{prefix}{src}"
    return src


def build_git_clone_command(
    repo_url: str,
    clone_path: str,
    settings: dict[str, Any] | None = None,
) -> str | None:
    """Cross-platform git clone command with optional proxy (-c http.proxy)."""
    cfg = settings or get_git_clone_settings()
    clone_url = apply_mirror_to_url(repo_url, cfg)
    rel = str(clone_path or "").strip()
    if not clone_url or not rel:
        return None
    mode = str(cfg.get("proxy_mode") or "none")
    parts = ["git"]
    if mode in ("local", "both"):
        http_proxy = str(cfg.get("http_proxy") or "").strip()
        https_proxy = str(cfg.get("https_proxy") or "").strip() or http_proxy
        if http_proxy:
            parts.extend(["-c", f"http.proxy={http_proxy}"])
        if https_proxy:
            parts.extend(["-c", f"https.proxy={https_proxy}"])
    parts.extend(["clone", clone_url, rel])
    return " ".join(parts)


def _path_installed(clone_path: str) -> bool:
    rel = str(clone_path or "").strip().replace("\\", "/")
    if not rel:
        return False
    root = get_project_root()
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return False
    if not target.is_dir():
        return False
    return any(target.iterdir())


def _config_enabled(keys: list[str] | None) -> bool:
    if not keys:
        return False
    for key in keys:
        parts = str(key).split(".")
        if not parts:
            continue
        val = config.get(parts[0], None)
        for part in parts[1:]:
            if not isinstance(val, dict):
                val = None
                break
            val = val.get(part)
        if val is True:
            return True
    return False


def _pip_command(entry: dict[str, Any]) -> str | None:
    req = str(entry.get("requirements_path") or "").strip()
    if not req:
        return None
    return f"uv pip install -r {req}"


def enrich_plugin_catalog(
    plugin_info: list[dict[str, Any]] | None = None,
    bridge_info: list[dict[str, str | bool]] | None = None,
) -> list[dict[str, Any]]:
    catalog = load_plugin_catalog()
    if not catalog:
        return []

    git_settings = get_git_clone_settings()
    loaded_names = {
        str(p.get("name") or "").strip().lower()
        for p in (plugin_info or [])
        if p and not p.get("builtin")
    }
    bridge_names = {str(b.get("name") or "").strip().lower() for b in (bridge_info or []) if b}
    directory = directory_plugin_load_status()
    candidates = {str(c).lower() for c in (directory.get("candidates") or [])}

    enriched: list[dict[str, Any]] = []
    for entry in catalog:
        name = str(entry.get("name") or "").strip()
        name_key = name.lower()
        clone_path = str(entry.get("clone_path") or "")
        on_disk = _path_installed(clone_path)
        disk_hint = clone_path.replace("plugins/local/", "") if clone_path else ""
        on_disk_candidate = any(disk_hint and disk_hint.lower() in c for c in candidates)
        loaded = name_key in loaded_names
        bridge_registered = name_key in bridge_names
        enabled_in_config = _config_enabled(entry.get("config_keys"))

        if loaded:
            status = "loaded"
        elif on_disk or on_disk_candidate:
            status = "installed_not_loaded"
        elif enabled_in_config:
            status = "missing_required"
        else:
            status = "not_installed"

        repo_url = resolve_repo_url()
        clone_url = apply_mirror_to_url(repo_url, git_settings) if repo_url else ""

        enriched.append(
            {
                **entry,
                "status": status,
                "loaded": loaded,
                "on_disk": on_disk or on_disk_candidate,
                "bridge_registered": bridge_registered,
                "enabled_in_config": enabled_in_config,
                "repo_url": repo_url or None,
                "clone_url": clone_url or None,
                "needs_repo_url": False,
                "clone_command": None,
                "pip_command": _pip_command(entry),
                "directory_scan_blocked": bool(directory.get("blocked")),
                "directory_hint": directory.get("hint"),
            }
        )
    return enriched


def gather_catalog_doctor_checks(
    plugin_info: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Checks for enabled bridge/capability without loaded plugin."""
    checks: list[dict[str, Any]] = []
    global_clone = enrich_git_clone_settings().get("clone_command")
    for entry in enrich_plugin_catalog(plugin_info=plugin_info):
        if entry.get("status") != "missing_required":
            continue
        label = str(entry.get("label") or entry.get("name") or "插件")
        clone_cmd = global_clone
        pip_cmd = entry.get("pip_command")
        parts = [f"已启用相关配置，但未检测到插件「{entry.get('name')}」运行。"]
        if not resolve_repo_url():
            parts.append("请在工作台「插件管理」填写 Git 仓库地址、保存后复制克隆命令。")
        elif clone_cmd:
            parts.append(f"安装：{clone_cmd}")
        if pip_cmd:
            parts.append(f"依赖：{pip_cmd}")
        parts.append("安装后重启服务（uv run ly）。")
        checks.append(
            {
                "id": f"plugin_catalog_{entry.get('id')}",
                "ok": False,
                "label": f"插件 {label}",
                "hint": " ".join(parts),
            }
        )
    return checks
