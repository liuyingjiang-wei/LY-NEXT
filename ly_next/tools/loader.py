"""Load user tool modules from a configured directory."""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Any

from ly_next.core.config import config, get_project_root
from ly_next.core.logger import get_logger
from ly_next.core.plugin.loader_security import (
    plugin_security_profile,
    sha256_file,
    trusted_plugin_hashes_map,
)
from ly_next.tools.base import BaseTool
from ly_next.tools.registry import ToolRegistry

logger = get_logger(__name__)


def _tool_plugin_dir() -> Path | None:
    raw = config.get("tools.plugin_dir")
    if raw is None or str(raw).strip() == "":
        return None
    path = Path(str(raw).strip())
    if not path.is_absolute():
        path = get_project_root() / path
    return path


def _discover_tool_modules(tool_dir: Path) -> list[Path]:
    if not tool_dir.is_dir():
        return []
    modules: list[Path] = []
    for item in tool_dir.iterdir():
        if item.is_file() and item.suffix == ".py" and not item.name.startswith("_"):
            modules.append(item)
        elif item.is_dir() and (item / "__init__.py").is_file():
            modules.append(item / "__init__.py")
    return sorted(modules, key=lambda p: p.name)


def _load_module(file_path: Path) -> Any | None:
    stem = file_path.stem
    module_name = f"ly_next_tool_plugin_{stem}"
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
        logger.error("[ToolLoader] failed to load %s: %s", file_path, e)
        return None


def _iter_tools_from_module(module: Any) -> list[Any]:
    found: list[Any] = []
    seen: set[int] = set()

    def add(candidate: Any) -> None:
        cid = id(candidate)
        if cid in seen:
            return
        if hasattr(candidate, "definition") and hasattr(candidate, "execute"):
            found.append(candidate)
            seen.add(cid)

    for attr_name in ("tools", "default", "TOOL", "tool"):
        if hasattr(module, attr_name):
            val = getattr(module, attr_name)
            if isinstance(val, list):
                for item in val:
                    add(item)
            else:
                add(val)

    for attr_name in dir(module):
        if attr_name.startswith("_"):
            continue
        attr = getattr(module, attr_name)
        if (
            inspect.isfunction(attr)
            and hasattr(attr, "definition")
            and hasattr(attr, "execute")
            or isinstance(attr, BaseTool)
        ):
            add(attr)

    return found


def register_tools_from_directory(registry: ToolRegistry) -> int:
    profile = config.get("tools.security_profile")
    if profile is None or str(profile).strip() == "":
        profile = plugin_security_profile()
    else:
        profile = str(profile).strip().lower()

    if profile == "production":
        logger.info("[ToolLoader] tools.security_profile=production: directory loading disabled")
        return 0

    tool_dir = _tool_plugin_dir()
    if tool_dir is None:
        return 0
    if not tool_dir.is_dir():
        logger.debug("[ToolLoader] tools.plugin_dir not found: %s", tool_dir)
        return 0

    trusted: dict[str, str] | None = None
    if profile == "verified":
        trusted = trusted_plugin_hashes_map()
        if not trusted:
            logger.warning("[ToolLoader] verified profile but trusted_module_hashes is empty")
            return 0

    root = tool_dir.resolve()
    registered = 0
    for module_path in _discover_tool_modules(tool_dir):
        if trusted is not None:
            rel = module_path.resolve().relative_to(root).as_posix()
            expected = trusted.get(rel)
            if expected is None:
                logger.warning("[ToolLoader] skip module not in trusted hashes: %s", rel)
                continue
            if sha256_file(module_path).lower() != expected.lower():
                logger.error("[ToolLoader] skip module (hash mismatch): %s", rel)
                continue

        module = _load_module(module_path)
        if module is None:
            continue
        for tool_obj in _iter_tools_from_module(module):
            try:
                registry.register(tool_obj)
                registered += 1
            except Exception as e:
                name = getattr(tool_obj, "name", module_path.name)
                logger.warning("[ToolLoader] failed to register %s: %s", name, e)

    if registered:
        logger.info("[ToolLoader] registered %s tools from %s", registered, tool_dir)
    return registered
