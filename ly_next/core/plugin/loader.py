"""Discover and load LY-NEXT plugins from directory, modules, and entry points."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

from ly_next.agent.factory import AgentFactory
from ly_next.api.base import APIRegistry
from ly_next.core.app_context import AppContext
from ly_next.core.config import config, get_project_root
from ly_next.core.logger import get_logger
from ly_next.core.plugin.builtin_plugin import BuiltinPlugin
from ly_next.core.plugin.directory_api_plugin import DirectoryAPIPlugin
from ly_next.core.plugin.loader_security import (
    plugin_security_profile,
    sha256_file,
    trusted_plugin_hashes_map,
)
from ly_next.core.plugin.protocol import LyNextPlugin
from ly_next.core.plugin.registry import PluginRegistry
from ly_next.core.plugin.tool_directory_plugin import ToolDirectoryPlugin
from ly_next.models.factory import LLMFactory

logger = get_logger(__name__)


def _plugins_enabled() -> bool:
    return bool(config.get("plugins.enabled", True))


def _entry_points_enabled() -> bool:
    return bool(config.get("plugins.entry_points", True))


def _plugin_dir() -> Path:
    raw = config.get("plugins.dir", "plugins")
    path = Path(str(raw or "plugins"))
    if not path.is_absolute():
        path = get_project_root() / path
    return path


def _plugin_extra_dirs() -> list[Path]:
    raw = config.get("plugins.extra_dirs")
    if raw is None:
        raw = ["plugins/local"]
    if not isinstance(raw, list):
        return []
    root = get_project_root()
    out: list[Path] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item or "").strip()
        if not text:
            continue
        path = Path(text)
        if not path.is_absolute():
            path = root / path
        try:
            key = str(path.resolve())
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def _plugin_search_dirs() -> list[Path]:
    primary = _plugin_dir()
    dirs = [primary]
    seen = {str(primary.resolve())}
    for path in _plugin_extra_dirs():
        try:
            key = str(path.resolve())
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        dirs.append(path)
    return dirs


def _ensure_plugins_import_path() -> list[Path]:
    dirs = _plugin_search_dirs()
    for plugin_dir in dirs:
        parent = str(plugin_dir.resolve())
        if parent not in sys.path:
            sys.path.insert(0, parent)
    return dirs


def _explicit_modules() -> list[str]:
    raw = config.get("plugins.modules") or []
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def _is_plugin_class(candidate: Any) -> bool:
    return (
        isinstance(candidate, type)
        and candidate is not LyNextPlugin
        and hasattr(candidate, "name")
        and callable(getattr(candidate, "register_tools", None))
    )


def _coerce_plugin(candidate: Any) -> LyNextPlugin | None:
    if isinstance(candidate, LyNextPlugin):
        return candidate
    if _is_plugin_class(candidate):
        try:
            return candidate()
        except TypeError:
            return None
    return None


def _extract_plugin_from_module(module: Any) -> LyNextPlugin | None:
    for attr_name in ("plugin", "Plugin", "default"):
        if not hasattr(module, attr_name):
            continue
        plugin = _coerce_plugin(getattr(module, attr_name))
        if plugin is not None:
            return plugin

    for attr_name in dir(module):
        if attr_name.startswith("_"):
            continue
        if attr_name in ("plugin", "Plugin", "default"):
            continue
        plugin = _coerce_plugin(getattr(module, attr_name))
        if plugin is not None:
            return plugin
    return None


def _load_module_from_file(file_path: Path, *, module_prefix: str = "ly_next_plugin") -> Any | None:
    stem = file_path.stem
    module_name = f"{module_prefix}_{stem}"
    if file_path.suffix == ".py":
        spec = importlib.util.spec_from_file_location(module_name, file_path)
    else:
        spec = importlib.util.spec_from_file_location(f"{module_name}.__init__", file_path)

    if not spec or not spec.loader:
        return None

    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    except Exception as e:
        logger.error("[PluginLoader] failed to load %s: %s", file_path, e)
        return None


def _discover_module_paths(plugin_dir: Path) -> list[Path]:
    if not plugin_dir.is_dir():
        return []

    modules: list[Path] = []
    for item in plugin_dir.iterdir():
        if item.is_file() and item.suffix == ".py" and not item.name.startswith("_"):
            modules.append(item)
        elif item.is_dir() and (item / "__init__.py").is_file():
            modules.append(item / "__init__.py")
    return sorted(modules, key=lambda p: p.name)


def _verify_module_path(module_path: Path, plugin_root: Path, trusted: dict[str, str]) -> bool:
    rel = module_path.resolve().relative_to(plugin_root.resolve()).as_posix()
    expected = trusted.get(rel)
    if expected is None:
        logger.warning("[PluginLoader] skip module not in trusted_module_hashes: %s", rel)
        return False
    actual = sha256_file(module_path).lower()
    if actual != expected.lower():
        logger.error("[PluginLoader] skip module (hash mismatch): %s", rel)
        return False
    return True


def _load_directory_plugins(registry: PluginRegistry) -> int:
    profile = plugin_security_profile()
    if profile == "production":
        logger.info(
            "[PluginLoader] plugins.security_profile=production: directory loading disabled"
        )
        return 0

    plugin_dirs = _ensure_plugins_import_path()
    if not any(d.is_dir() for d in plugin_dirs):
        logger.debug("[PluginLoader] no plugin directories found under %s", plugin_dirs)
        return 0

    trusted: dict[str, str] | None = None
    if profile == "verified":
        trusted = trusted_plugin_hashes_map()
        if not trusted:
            logger.warning(
                "[PluginLoader] verified profile but plugins.trusted_module_hashes is empty"
            )
            return 0

    loaded = 0
    seen_names: set[str] = set()
    for plugin_dir in plugin_dirs:
        if not plugin_dir.is_dir():
            continue
        plugin_root = plugin_dir.resolve()
        for module_path in _discover_module_paths(plugin_dir):
            if trusted is not None and not _verify_module_path(
                module_path, plugin_root, trusted
            ):
                continue
            pkg_dir = module_path.parent if module_path.name == "__init__.py" else None
            if pkg_dir and pkg_dir.is_dir() and (pkg_dir / "__init__.py").is_file():
                try:
                    module = importlib.import_module(pkg_dir.name)
                except Exception as e:
                    logger.error(
                        "[PluginLoader] failed to import package %s: %s", pkg_dir.name, e
                    )
                    continue
            else:
                module = _load_module_from_file(module_path)
                if module is None:
                    continue
            plugin = _extract_plugin_from_module(module)
            if plugin is None:
                if getattr(module, "tools", None) is not None and not hasattr(
                    module, "plugin"
                ):
                    logger.debug(
                        "[PluginLoader] skip tool-only module %s (belongs in tools.plugin_dir)",
                        module_path.name,
                    )
                    continue
                logger.warning("[PluginLoader] no plugin found in %s", module_path)
                continue
            if plugin.name in seen_names:
                continue
            seen_names.add(plugin.name)
            registry.register(plugin)
            loaded += 1
    return loaded


def _load_explicit_module_plugins(registry: PluginRegistry) -> int:
    loaded = 0
    for qualified in _explicit_modules():
        try:
            module = importlib.import_module(qualified)
        except Exception as e:
            logger.error("[PluginLoader] failed to import plugins.modules %s: %s", qualified, e)
            continue
        plugin = _extract_plugin_from_module(module)
        if plugin is None:
            logger.warning("[PluginLoader] no plugin in module %s", qualified)
            continue
        registry.register(plugin, replace=True)
        loaded += 1
    return loaded


def _load_entry_point_plugins(registry: PluginRegistry) -> int:
    if not _entry_points_enabled():
        return 0
    if plugin_security_profile() == "production":
        logger.info("[PluginLoader] entry_points disabled in production profile")
        return 0

    try:
        from importlib.metadata import entry_points
    except ImportError:
        return 0

    try:
        eps = entry_points(group="ly_next.plugins")
    except TypeError:
        eps = entry_points().get("ly_next.plugins", [])

    loaded = 0
    for ep in eps:
        try:
            factory = ep.load()
            plugin = _coerce_plugin(factory() if callable(factory) else factory)
            if plugin is None and isinstance(factory, type):
                plugin = _coerce_plugin(factory)
            if plugin is None:
                logger.warning("[PluginLoader] entry point %s is not a LyNextPlugin", ep.name)
                continue
            registry.register(plugin, replace=True)
            loaded += 1
        except Exception as e:
            logger.error("[PluginLoader] entry point %s failed: %s", ep.name, e)
    return loaded


def _apply_plugin_registrations(
    registry: PluginRegistry,
    ctx: AppContext,
    *,
    api_registry: APIRegistry | None = None,
) -> None:
    for plugin in registry.list_plugins():
        try:
            plugin.register_tools(ctx.tool_registry, ctx)
            plugin.register_agents(AgentFactory, ctx)
            plugin.register_llm_providers(LLMFactory, ctx)
            if api_registry is not None:
                plugin.register_apis(api_registry, ctx)
            plugin.register_bridges(registry.bridge_registry, ctx)
        except Exception as e:
            logger.error(
                "[PluginLoader] registration failed for %s: %s",
                plugin.name,
                e,
                exc_info=True,
            )
            raise


class PluginLoader:
    def __init__(self) -> None:
        self.registry = PluginRegistry()

    def load_all(
        self,
        ctx: AppContext,
        *,
        api_registry: APIRegistry | None = None,
        include_builtin: bool = True,
    ) -> PluginRegistry:
        if not _plugins_enabled():
            logger.info("[PluginLoader] plugins.enabled=false; loading builtin only")
            include_builtin = True

        if include_builtin:
            self.registry.register(BuiltinPlugin())
            self.registry.register(ToolDirectoryPlugin())
            self.registry.register(DirectoryAPIPlugin())

        if _plugins_enabled():
            n_dir = _load_directory_plugins(self.registry)
            n_mod = _load_explicit_module_plugins(self.registry)
            n_ep = _load_entry_point_plugins(self.registry)
            logger.info(
                "[PluginLoader] loaded %s directory + %s modules + %s entry-point plugins",
                n_dir,
                n_mod,
                n_ep,
            )

        _apply_plugin_registrations(self.registry, ctx, api_registry=api_registry)
        ctx.set_plugin_registry(self.registry)
        if api_registry is not None:
            self.registry.api_registry = api_registry
        return self.registry
