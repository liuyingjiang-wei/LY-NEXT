"""Remote MCP config merge; tool loading in langchain_adapter_bridge."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from ly_next.core.config import config
from ly_next.core.logger import get_logger

logger = get_logger(__name__)

_remote_mcp_loaded = False
_remote_mcp_lock = asyncio.Lock()


def is_remote_mcp_loaded() -> bool:
    return _remote_mcp_loaded


def remote_mcp_startup_load_enabled() -> bool:
    tools = config.get("tools") or {}
    mcp = tools.get("mcp") if isinstance(tools, dict) else {}
    if not isinstance(mcp, dict):
        return False
    return bool(mcp.get("load_remote_on_startup", False))


def remote_mcp_configured() -> bool:
    tools = config.get("tools") or {}
    mcp = tools.get("mcp") if isinstance(tools, dict) else {}
    if not isinstance(mcp, dict):
        return False
    remote = mcp.get("remote")
    return isinstance(remote, dict) and bool(remote.get("enabled"))


async def ensure_remote_mcp_loaded() -> None:
    """Load remote MCP tools once per process (stdio/HTTP connect + tool list)."""
    global _remote_mcp_loaded
    if _remote_mcp_loaded:
        return
    async with _remote_mcp_lock:
        if _remote_mcp_loaded:
            return
        await load_remote_mcp_tools()


async def reload_remote_mcp_tools() -> None:
    """Re-read config and reconnect (e.g. after workbench MCP settings save)."""
    global _remote_mcp_loaded
    async with _remote_mcp_lock:
        _remote_mcp_loaded = False
        await load_remote_mcp_tools()


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", (name or "").strip().lower()).strip("-")
    return s or "remote"


def _block_to_obj(block: Any) -> dict[str, Any] | None:
    if isinstance(block, str):
        try:
            block = json.loads(block)
        except json.JSONDecodeError:
            return None
    if not isinstance(block, dict):
        return None
    if "config" in block and isinstance(block["config"], dict):
        return block["config"]
    return block


def merge_mcp_server_blocks(blocks: list[Any]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for raw in blocks or []:
        obj = _block_to_obj(raw)
        if not obj:
            continue
        m = obj.get("mcpServers")
        if not isinstance(m, dict) or isinstance(m, list):
            continue
        for k, v in m.items():
            key = _slug(str(k))
            if not key or not isinstance(v, dict):
                continue
            if key in merged:
                logger.warning(
                    "MCP 配置块中服务器名 %s 重复，后一块将覆盖前一块（请为每个服务器使用不同名称）",
                    key,
                )
            merged[key] = v
    return merged


def legacy_servers_to_blocks(legacy: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(legacy, list):
        return out
    for i, row in enumerate(legacy):
        if not isinstance(row, dict) or row.get("enabled") is False:
            continue
        url = str(row.get("url") or "").strip()
        if not url:
            continue
        key = _slug(str(row.get("name") or f"srv{i}"))
        hdr: dict[str, str] = {}
        ah = str(row.get("auth_header") or "").strip()
        at = str(row.get("auth_token") or "").strip()
        if ah and at:
            hdr[ah] = at
        out.append(
            {"config": {"mcpServers": {key: {"url": url, "transport": "http", "headers": hdr}}}}
        )
    return out


def clear_remote_mcp_tools() -> None:
    global _remote_mcp_loaded
    from ly_next.mcp.langchain_adapter_bridge import clear_mcp_adapter_state
    from ly_next.mcp.server import mcp_server
    from ly_next.tools.registry import get_tool_registry

    for k in list(mcp_server.protocol._tools.keys()):
        if k.startswith("remote-mcp."):
            del mcp_server.protocol._tools[k]
    clear_mcp_adapter_state(get_tool_registry())
    _remote_mcp_loaded = False


async def load_remote_mcp_tools() -> None:
    global _remote_mcp_loaded
    from ly_next.mcp.langchain_adapter_bridge import load_mcp_tools_via_langchain
    from ly_next.tools.registry import get_tool_registry

    clear_remote_mcp_tools()
    try:
        await load_mcp_tools_via_langchain(get_tool_registry())
        _remote_mcp_loaded = True
    except Exception as e:
        logger.warning("MCP 工具加载失败（langchain-mcp-adapters）: %s", e)
