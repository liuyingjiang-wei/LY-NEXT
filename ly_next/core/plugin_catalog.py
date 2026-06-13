"""Official plugin catalog — install hints and doctor/workbench integration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ly_next.core.config import config, get_project_root
from ly_next.core.plugin.loader import directory_plugin_load_status

_CATALOG_PATH = get_project_root() / "plugins" / "catalog.json"


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


def _clone_command(entry: dict[str, Any]) -> str | None:
    repo = str(entry.get("repo_url") or "").strip()
    clone_path = str(entry.get("clone_path") or "").strip()
    if not repo or not clone_path:
        return None
    return f"git clone {repo} {clone_path}"


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

    loaded_names = {
        str(p.get("name") or "").strip().lower()
        for p in (plugin_info or [])
        if p and not p.get("builtin")
    }
    bridge_names = {
        str(b.get("name") or "").strip().lower() for b in (bridge_info or []) if b
    }
    directory = directory_plugin_load_status()
    candidates = {str(c).lower() for c in (directory.get("candidates") or [])}

    enriched: list[dict[str, Any]] = []
    for entry in catalog:
        name = str(entry.get("name") or "").strip()
        name_key = name.lower()
        clone_path = str(entry.get("clone_path") or "")
        on_disk = _path_installed(clone_path)
        disk_hint = clone_path.replace("plugins/local/", "") if clone_path else ""
        on_disk_candidate = any(
            disk_hint and disk_hint.lower() in c for c in candidates
        )
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

        enriched.append(
            {
                **entry,
                "status": status,
                "loaded": loaded,
                "on_disk": on_disk or on_disk_candidate,
                "bridge_registered": bridge_registered,
                "enabled_in_config": enabled_in_config,
                "clone_command": _clone_command(entry),
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
    for entry in enrich_plugin_catalog(plugin_info=plugin_info):
        if entry.get("status") != "missing_required":
            continue
        label = str(entry.get("label") or entry.get("name") or "插件")
        clone_cmd = entry.get("clone_command")
        pip_cmd = entry.get("pip_command")
        parts = [f"已启用相关配置，但未检测到插件「{entry.get('name')}」运行。"]
        if clone_cmd:
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
