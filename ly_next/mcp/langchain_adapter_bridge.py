from __future__ import annotations

from contextlib import suppress
from typing import Any

from langchain_core.tools import BaseTool as LangChainBaseTool

from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.mcp.remote_bridge import legacy_servers_to_blocks, merge_mcp_server_blocks
from ly_next.mcp.server import MCPTool, mcp_server
from ly_next.tools.base import BaseTool, ToolDefinition, ToolResult

logger = get_logger(__name__)

_cached_lc_mcp_tools: list[LangChainBaseTool] = []
_registered_registry_names: list[str] = []
_registered_mcp_protocol_names: list[str] = []


def _schema_from_lc_tool(t: LangChainBaseTool) -> dict[str, Any]:
    schema = getattr(t, "args_schema", None)
    if schema is not None:
        try:
            return schema.model_json_schema()
        except Exception:
            pass
    return {"type": "object", "properties": {}, "additionalProperties": True}


class LangChainMCPToolBridge(BaseTool):
    def __init__(self, lc_tool: LangChainBaseTool):
        self._lc = lc_tool
        self._definition = ToolDefinition(
            name=lc_tool.name,
            description=(getattr(lc_tool, "description", None) or "").strip(),
            parameters=_schema_from_lc_tool(lc_tool),
            category="mcp",
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            out = await self._lc.ainvoke(kwargs)
            return ToolResult(success=True, result=out)
        except Exception as e:
            logger.warning("MCP tool %s failed: %s", self._lc.name, e)
            return ToolResult(success=False, error=str(e))


def _server_block_to_connection(name: str, cfg: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(cfg, dict):
        return None
    cmd = str(cfg.get("command") or "").strip()
    if cmd:
        args = cfg.get("args")
        if not isinstance(args, list):
            args = []
        out: dict[str, Any] = {
            "transport": "stdio",
            "command": cmd,
            "args": [str(x) for x in args],
        }
        if isinstance(cfg.get("env"), dict):
            out["env"] = {str(k): str(v) for k, v in cfg["env"].items()}
        if cfg.get("cwd"):
            out["cwd"] = str(cfg["cwd"])
        return out

    url = str(cfg.get("url") or "").strip()
    if not url:
        return None

    transport = str(cfg.get("transport") or "http").lower()
    headers: dict[str, str] = {}
    hdrs = cfg.get("headers")
    if isinstance(hdrs, dict):
        headers = {str(k): str(v) for k, v in hdrs.items()}

    if transport in ("websocket", "ws"):
        return {"transport": "websocket", "url": url}
    if transport == "sse":
        base: dict[str, Any] = {"transport": "sse", "url": url}
        if headers:
            base["headers"] = headers
        return base
    return {"transport": "http", "url": url, **({"headers": headers} if headers else {})}


def get_cached_langchain_mcp_tools() -> tuple[LangChainBaseTool, ...]:
    return tuple(_cached_lc_mcp_tools)


def clear_mcp_adapter_state(registry: Any) -> None:
    global _cached_lc_mcp_tools, _registered_registry_names, _registered_mcp_protocol_names
    for n in _registered_registry_names:
        with suppress(Exception):
            registry.unregister(n)
    for n in _registered_mcp_protocol_names:
        mcp_server.protocol._tools.pop(n, None)
    _registered_registry_names.clear()
    _registered_mcp_protocol_names.clear()
    _cached_lc_mcp_tools.clear()


async def load_mcp_tools_via_langchain(registry: Any) -> int:
    global _cached_lc_mcp_tools

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError as e:
        raise RuntimeError("请安装 langchain-mcp-adapters: uv sync") from e

    clear_mcp_adapter_state(registry)

    tools_root = config.get("tools") or {}
    mcp_cfg = tools_root.get("mcp") if isinstance(tools_root, dict) else None
    if not isinstance(mcp_cfg, dict):
        return 0
    remote = mcp_cfg.get("remote")
    if not isinstance(remote, dict) or not remote.get("enabled"):
        return 0

    blocks: list[Any] = []
    ms = remote.get("mcpServers")
    if isinstance(ms, list):
        blocks = list(ms)
    if not blocks:
        legacy = mcp_cfg.get("servers")
        if isinstance(legacy, list) and legacy:
            blocks = legacy_servers_to_blocks(legacy)

    merged = merge_mcp_server_blocks(blocks)
    if not merged:
        return 0

    use_prefix = bool(mcp_cfg.get("langgraph_tool_name_prefix", True))
    connections: dict[str, dict[str, Any]] = {}
    for name, cfg in merged.items():
        if not isinstance(cfg, dict):
            continue
        conn = _server_block_to_connection(name, cfg)
        if conn:
            connections[name] = conn
        else:
            logger.warning("MCP 配置缺少 url+transport 或 command+args，已跳过: %s", name)

    if not connections:
        return 0

    client = MultiServerMCPClient(connections=connections, tool_name_prefix=use_prefix)
    lc_tools = await client.get_tools()
    _cached_lc_mcp_tools = list(lc_tools)

    n_reg = 0
    for lc in lc_tools:
        bridge = LangChainMCPToolBridge(lc)
        try:
            registry.register(bridge)
            _registered_registry_names.append(bridge.definition.name)
            n_reg += 1
        except Exception as e:
            logger.warning("注册 MCP 工具到 registry 失败 %s: %s", getattr(lc, "name", ""), e)
            continue

        def _make_handler(t: LangChainBaseTool):
            async def _h(**kwargs: Any) -> Any:
                return await t.ainvoke(kwargs)

            return _h

        try:
            mcp_server.protocol.register_tool(
                MCPTool(
                    name=lc.name,
                    description=(getattr(lc, "description", None) or "")[:2000],
                    input_schema=_schema_from_lc_tool(lc),
                    handler=_make_handler(lc),
                )
            )
            _registered_mcp_protocol_names.append(lc.name)
        except Exception as e:
            logger.warning("注册 MCP 工具到协议层失败 %s: %s", lc.name, e)

    if n_reg:
        logger.info("langchain-mcp-adapters: 已加载 %s 个 MCP 工具", n_reg)
    return n_reg
