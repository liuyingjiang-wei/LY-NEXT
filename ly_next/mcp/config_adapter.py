"""Adapt incomplete vendor MCP docs (e.g. ModelScope) to runnable stdio commands."""

from __future__ import annotations

import asyncio
import re
import shutil
from typing import Any

from ly_next.core.config import config
from ly_next.core.logger import get_logger

logger = get_logger(__name__)


def _vendor_adapt_probe_enabled() -> bool:
    tools = config.get("tools") or {}
    mcp = tools.get("mcp") if isinstance(tools, dict) else {}
    if not isinstance(mcp, dict):
        return False
    return bool(mcp.get("vendor_adapt_probe", False))

_PACKAGE_SPEC_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(@[A-Za-z0-9._-]+)?$")
_EXECUTABLE_LIST_RE = re.compile(
    r"following executables are available:\s*(.+?)(?:\nUse `|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_EXECUTABLE_LINE_RE = re.compile(r"^\s*-\s+([A-Za-z0-9_.-]+)", re.MULTILINE)
_PROBE_CACHE: dict[str, str] = {}


def _basename(cmd: str) -> str:
    return (cmd or "").strip().replace("\\", "/").rsplit("/", 1)[-1].lower()


def _looks_like_package_spec(value: str) -> bool:
    token = (value or "").strip()
    return bool(token) and bool(_PACKAGE_SPEC_RE.match(token))


def _guess_uvx_executable(package_spec: str) -> str:
    pkg = package_spec.split("@", 1)[0].strip()
    if not pkg:
        return ""
    return pkg.replace("-", "_")


def _parse_uvx_probe_output(text: str) -> str | None:
    if not text:
        return None
    block = _EXECUTABLE_LIST_RE.search(text)
    if block:
        names = _EXECUTABLE_LINE_RE.findall(block.group(1))
        if names:
            return names[0].removesuffix(".exe")
    for line in text.splitlines():
        if line.strip().startswith("Use `uvx --from"):
            m = re.search(r"uvx --from [^\s]+ ([A-Za-z0-9_.-]+)", line)
            if m:
                return m.group(1).removesuffix(".exe")
    return None


async def _probe_uvx_executable(package_spec: str, *, timeout: float = 60.0) -> str | None:
    cached = _PROBE_CACHE.get(package_spec)
    if cached:
        return cached

    uvx = shutil.which("uvx")
    if not uvx:
        return None

    try:
        proc = await asyncio.create_subprocess_exec(
            uvx,
            package_spec,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (TimeoutError, OSError) as exc:
        logger.warning("[mcp] uvx probe failed for %s: %s", package_spec, exc)
        return None

    text = (stderr or b"").decode("utf-8", errors="replace")
    exe = _parse_uvx_probe_output(text)
    if exe:
        _PROBE_CACHE[package_spec] = exe
    return exe


def _adapt_uvx_args(args: list[str]) -> list[str] | None:
    if not args:
        return None
    if str(args[0]).strip() in ("--from", "-f"):
        return None
    if len(args) != 1:
        return None
    spec = str(args[0]).strip()
    if not _looks_like_package_spec(spec):
        return None
    exe = _guess_uvx_executable(spec)
    if not exe:
        return None
    return ["--from", spec, exe]


def _adapt_uv_run_args(args: list[str]) -> list[str] | None:
    if len(args) != 2 or str(args[0]).strip().lower() != "run":
        return None
    spec = str(args[1]).strip()
    if not _looks_like_package_spec(spec):
        return None
    exe = _guess_uvx_executable(spec)
    if not exe:
        return None
    return ["run", "--from", spec, exe]


def _adapt_npx_args(args: list[str]) -> list[str] | None:
    if len(args) != 1:
        return None
    pkg = str(args[0]).strip()
    if not pkg or pkg in ("-y", "-ys"):
        return None
    if pkg.startswith("-"):
        return None
    return ["-y", pkg]


async def adapt_stdio_command_async(cmd: str, args: list[str]) -> tuple[str, list[str]]:
    base = _basename(cmd)
    normalized = [str(x) for x in args]

    if base == "uvx":
        adapted = _adapt_uvx_args(normalized)
        if adapted:
            spec = adapted[1]
            exe = _guess_uvx_executable(spec)
            if _vendor_adapt_probe_enabled():
                probed = await _probe_uvx_executable(spec)
                exe = probed or exe
            adapted[-1] = exe
            logger.info(
                "[mcp] adapted ModelScope-style uvx: uvx %s -> uvx --from %s %s",
                normalized[0],
                spec,
                adapted[-1],
            )
            return "uvx", adapted

    if base == "uv":
        adapted = _adapt_uv_run_args(normalized)
        if adapted:
            logger.info(
                "[mcp] adapted ModelScope-style uv run: uv %s -> uv run --from %s %s",
                " ".join(normalized),
                adapted[2],
                adapted[-1],
            )
            return "uv", adapted

    if base in ("npx", "npm"):
        adapted = _adapt_npx_args(normalized)
        if adapted:
            logger.info(
                "[mcp] adapted ModelScope-style npx: npx %s -> npx -y %s",
                normalized[0],
                adapted[1],
            )
            return cmd, adapted

    return cmd, normalized


def adapt_stdio_command(cmd: str, args: list[str]) -> tuple[str, list[str]]:
    """Sync wrapper for contexts without a running loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(adapt_stdio_command_async(cmd, args))
    return cmd, list(args)


async def adapt_mcp_server_config_async(name: str, cfg: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(cfg, dict):
        return cfg
    cmd = str(cfg.get("command") or "").strip()
    if not cmd:
        return cfg
    raw_args = cfg.get("args")
    args = [str(x) for x in raw_args] if isinstance(raw_args, list) else []
    new_cmd, new_args = await adapt_stdio_command_async(cmd, args)
    if new_cmd == cmd and new_args == args:
        return cfg
    out = dict(cfg)
    out["command"] = new_cmd
    out["args"] = new_args
    logger.info("[mcp] server %s stdio command adapted for vendor doc compatibility", name)
    return out


async def adapt_merged_mcp_servers(merged: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, cfg in merged.items():
        if isinstance(cfg, dict):
            out[name] = await adapt_mcp_server_config_async(name, cfg)
        else:
            out[name] = cfg
    return out
