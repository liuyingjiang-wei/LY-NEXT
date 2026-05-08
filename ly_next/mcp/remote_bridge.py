"""MCP 远端配置解析；工具加载见 langchain_adapter_bridge（langchain-mcp-adapters）。"""

from __future__ import annotations

import json
import re
from typing import Any

from ly_next.core.logger import get_logger

logger = get_logger(__name__)


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
            if key and isinstance(v, dict):
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
    from ly_next.mcp.langchain_adapter_bridge import clear_mcp_adapter_state
    from ly_next.mcp.server import mcp_server
    from ly_next.tools.registry import get_tool_registry

    for k in list(mcp_server.protocol._tools.keys()):
        if k.startswith("remote-mcp."):
            del mcp_server.protocol._tools[k]
    clear_mcp_adapter_state(get_tool_registry())


async def load_remote_mcp_tools() -> None:
    from ly_next.mcp.langchain_adapter_bridge import load_mcp_tools_via_langchain
    from ly_next.tools.registry import get_tool_registry

    clear_remote_mcp_tools()
    try:
        await load_mcp_tools_via_langchain(get_tool_registry())
    except Exception as e:
        logger.warning("MCP 工具加载失败（langchain-mcp-adapters）: %s", e)
