from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx

from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.mcp.server import MCPTool, mcp_server

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
    for k in list(mcp_server.protocol._tools.keys()):
        if k.startswith("remote-mcp."):
            del mcp_server.protocol._tools[k]


def _normalize_tool_result(raw: Any) -> Any:
    if raw is None:
        return {"ok": False, "error": "empty result"}
    if isinstance(raw, dict):
        parts = raw.get("content")
        if isinstance(parts, list) and parts:
            t0 = parts[0]
            if isinstance(t0, dict) and t0.get("type") == "text":
                txt = t0.get("text")
                if isinstance(txt, str) and txt.strip():
                    try:
                        return json.loads(txt)
                    except json.JSONDecodeError:
                        return {"text": txt}
        return raw
    return raw


async def _jsonrpc_http(
    url: str, method: str, params: dict[str, Any], headers: dict[str, str]
) -> dict[str, Any]:
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    h = {**headers, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url.rstrip("/"), json=body, headers=h)
        r.raise_for_status()
        return r.json()


async def _jsonrpc_ws(
    url: str, method: str, params: dict[str, Any], headers: dict[str, str]
) -> dict[str, Any]:
    try:
        import websockets
    except ImportError:
        raise RuntimeError("install websockets for remote MCP over ws") from None

    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    h = [(k, v) for k, v in headers.items() if isinstance(k, str) and isinstance(v, str)]
    async with websockets.connect(url, additional_headers=dict(h), max_size=10_000_000) as ws:
        await ws.send(payload)
        raw = await asyncio.wait_for(ws.recv(), timeout=60.0)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    return json.loads(raw)


async def _jsonrpc_remote(
    url: str, transport: str, method: str, params: dict[str, Any], headers: dict[str, str]
) -> dict[str, Any]:
    t = (transport or "http").lower()
    if t in ("websocket", "ws"):
        return await _jsonrpc_ws(url, method, params, headers)
    return await _jsonrpc_http(url, method, params, headers)


def _make_remote_tool_handler(url: str, headers: dict[str, str], transport: str, tool_name: str):
    hdr = dict(headers)

    async def handler(**kwargs: Any) -> Any:
        out = await _jsonrpc_remote(
            url, transport, "tools/call", {"name": tool_name, "arguments": kwargs}, hdr
        )
        if isinstance(out, dict) and out.get("error"):
            er = out["error"]
            raise RuntimeError(er.get("message", str(er)) if isinstance(er, dict) else str(er))
        return _normalize_tool_result(out.get("result"))

    return handler


async def _register_http_like_server(server_name: str, cfg: dict[str, Any]) -> None:
    url = str(cfg.get("url") or "").strip()
    if not url:
        return
    hdrs = cfg.get("headers")
    headers = {str(k): str(v) for k, v in (hdrs.items() if isinstance(hdrs, dict) else [])}
    transport = str(cfg.get("transport") or "http").lower()

    data = await _jsonrpc_remote(url, transport, "tools/list", {}, headers)
    if isinstance(data, dict) and data.get("error"):
        err = data["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        raise RuntimeError(msg)
    res = data.get("result") if isinstance(data, dict) else None
    if not isinstance(res, dict):
        res = {}
    tool_list = res.get("tools") or []
    if not isinstance(tool_list, list):
        return

    for t in tool_list:
        if not isinstance(t, dict):
            continue
        tn = str(t.get("name") or "").strip()
        if not tn:
            continue
        fq = f"remote-mcp.{server_name}.{tn}"
        desc = str(t.get("description") or "")
        schema = t.get("inputSchema") or t.get("input_schema") or {}
        if not isinstance(schema, dict):
            schema = {}

        mcp_server.protocol.register_tool(
            MCPTool(
                name=fq,
                description=desc,
                input_schema=schema,
                handler=_make_remote_tool_handler(url, headers, transport, tn),
            )
        )


async def load_remote_mcp_tools() -> None:
    clear_remote_mcp_tools()
    tools_root = config.get("tools") or {}
    mcp_cfg = tools_root.get("mcp") if isinstance(tools_root, dict) else None
    if not isinstance(mcp_cfg, dict):
        return
    remote = mcp_cfg.get("remote")
    blocks: list[Any] = []
    enabled = False
    if isinstance(remote, dict):
        enabled = bool(remote.get("enabled"))
        ms = remote.get("mcpServers")
        if isinstance(ms, list):
            blocks = list(ms)
    if not enabled:
        return
    if not blocks:
        legacy = mcp_cfg.get("servers")
        if isinstance(legacy, list) and legacy:
            blocks = legacy_servers_to_blocks(legacy)
    merged = merge_mcp_server_blocks(blocks)
    if not merged:
        return
    for name, cfg in merged.items():
        if not isinstance(cfg, dict):
            continue
        if cfg.get("command"):
            logger.warning("remote MCP stdio skipped (%s): use url + http/ws", name)
            continue
        try:
            await _register_http_like_server(name, cfg)
            n = sum(1 for k in mcp_server.protocol._tools if k.startswith(f"remote-mcp.{name}."))
            if n:
                logger.info("remote MCP registered: %s (%d tools)", name, n)
        except Exception as e:
            logger.warning("remote MCP failed (%s): %s", name, e)
