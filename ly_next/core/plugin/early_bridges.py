"""Register message-bridge routes before FastAPI include_router (NapCat WS, etc.)."""

from __future__ import annotations

import importlib
from typing import Any

from ly_next.core.app_context import AppContext
from ly_next.core.bridge_log import blog, get_bridge_logger
from ly_next.core.plugin.bridge_registry import BridgeRegistry
from ly_next.core.plugin.loader import (
    _coerce_plugin,
    _discover_module_paths,
    _ensure_plugins_import_path,
    _entry_points_enabled,
    _explicit_modules,
    _extract_plugin_from_module,
    _plugins_enabled,
)
from ly_next.core.plugin.loader_security import plugin_security_profile, trusted_plugin_hashes_map

logger = get_bridge_logger(__name__)


def _load_directory_bridge_plugins(registry: BridgeRegistry, ctx: AppContext) -> None:
    if not _plugins_enabled():
        return
    profile = plugin_security_profile()
    if profile == "production":
        return
    if profile == "verified" and not trusted_plugin_hashes_map():
        return
    plugin_dirs = _ensure_plugins_import_path()
    if not any(d.is_dir() for d in plugin_dirs):
        return
    seen_names: set[str] = set()
    for plugin_dir in plugin_dirs:
        if not plugin_dir.is_dir():
            continue
        for module_path in _discover_module_paths(plugin_dir):
            pkg_dir = module_path.parent if module_path.name == "__init__.py" else None
            if pkg_dir and pkg_dir.is_dir() and (pkg_dir / "__init__.py").is_file():
                try:
                    module = importlib.import_module(pkg_dir.name)
                except Exception as e:
                    logger.error("[EarlyBridges] failed to import %s: %s", pkg_dir.name, e)
                    continue
            else:
                from ly_next.core.plugin import loader as pl

                module = pl._load_module_from_file(module_path)
                if module is None:
                    continue
            plugin = _extract_plugin_from_module(module)
            if plugin is None:
                continue
            if plugin.name in seen_names:
                continue
            seen_names.add(plugin.name)
            try:
                plugin.register_bridges(registry, ctx)
            except Exception as e:
                logger.error("[EarlyBridges] register_bridges failed for %s: %s", plugin.name, e)


def _load_module_bridge_plugins(registry: BridgeRegistry, ctx: AppContext) -> None:
    for qualified in _explicit_modules():
        try:
            module = importlib.import_module(qualified)
        except Exception as e:
            logger.error("[EarlyBridges] import %s failed: %s", qualified, e)
            continue
        plugin = _extract_plugin_from_module(module)
        if plugin is None:
            continue
        plugin.register_bridges(registry, ctx)


def _load_entry_point_bridge_plugins(registry: BridgeRegistry, ctx: AppContext) -> None:
    if not _entry_points_enabled():
        return
    try:
        from importlib.metadata import entry_points
    except ImportError:
        return
    try:
        eps = entry_points(group="ly_next.plugins")
    except TypeError:
        eps = entry_points().get("ly_next.plugins", [])

    for ep in eps:
        try:
            factory = ep.load()
            plugin = _coerce_plugin(factory() if callable(factory) else factory)
            if plugin is None and isinstance(factory, type):
                plugin = _coerce_plugin(factory)
            if plugin is None:
                continue
            plugin.register_bridges(registry, ctx)
        except Exception as e:
            logger.error("[EarlyBridges] entry point %s failed: %s", ep.name, e)


def bootstrap_message_bridges(ws_router: Any, app: Any) -> tuple[BridgeRegistry, list[str]]:
    registry = BridgeRegistry()
    ctx = AppContext.create()
    _load_directory_bridge_plugins(registry, ctx)
    _load_module_bridge_plugins(registry, ctx)
    _load_entry_point_bridge_plugins(registry, ctx)

    paths: list[str] = []
    for bridge in registry.enabled():
        try:
            paths.extend(bridge.attach_routes(ws_router, app))
        except Exception as e:
            logger.error("[EarlyBridges] attach_routes failed for %s: %s", bridge.name, e)
    if paths:
        blog(logger, "onebot11", "success", f"early WS paths: {', '.join(paths)}")
    return registry, paths


def collect_bridge_ws_exempt_paths(app: Any) -> list[str]:
    paths = list(getattr(app.state, "bridge_ws_paths", None) or [])
    legacy = getattr(app.state, "onebot11_ws_paths", None) or []
    for p in legacy:
        if p not in paths:
            paths.append(p)
    return paths
