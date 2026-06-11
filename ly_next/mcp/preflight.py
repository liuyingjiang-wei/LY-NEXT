"""Preflight checks for remote MCP stdio runtimes (Node / uv / Python)."""

from __future__ import annotations

import shutil
from typing import Any

from ly_next.core.config import config
from ly_next.mcp.remote_bridge import merge_mcp_server_blocks

_NODE_CMDS = frozenset({"npx", "npm", "node", "pnpm", "yarn"})
_UV_CMDS = frozenset({"uv", "uvx"})
_PY_CMDS = frozenset({"python", "python3", "py"})


def _mcp_remote_blocks() -> list[Any]:
    tools = config.get("tools") or {}
    if not isinstance(tools, dict):
        return []
    mcp = tools.get("mcp") or {}
    if not isinstance(mcp, dict):
        return []
    remote = mcp.get("remote") or {}
    if not isinstance(remote, dict) or not remote.get("enabled"):
        return []
    ms = remote.get("mcpServers")
    return list(ms) if isinstance(ms, list) else []


def _stdio_servers() -> list[tuple[str, str, list[str]]]:
    merged = merge_mcp_server_blocks(_mcp_remote_blocks())
    out: list[tuple[str, str, list[str]]] = []
    for name, cfg in merged.items():
        if not isinstance(cfg, dict):
            continue
        cmd = str(cfg.get("command") or "").strip()
        if not cmd:
            continue
        args = cfg.get("args")
        arg_list = [str(x) for x in args] if isinstance(args, list) else []
        out.append((name, cmd, arg_list))
    return out


def _needs_node(cmd: str, args: list[str]) -> bool:
    base = cmd.lower().split("\\")[-1].split("/")[-1]
    if base in _NODE_CMDS:
        return True
    if base == "cmd" and args and str(args[0]).lower() in ("/c", "/k"):
        joined = " ".join(args).lower()
        return "npx" in joined or "npm" in joined or "node " in joined
    return False


def _needs_uv(cmd: str) -> bool:
    base = cmd.lower().split("\\")[-1].split("/")[-1]
    return base in _UV_CMDS


def _needs_python(cmd: str) -> bool:
    base = cmd.lower().split("\\")[-1].split("/")[-1]
    return base in _PY_CMDS


def gather_mcp_runtime_checks() -> list[dict[str, Any]]:
    """Return doctor-style checks when remote MCP uses stdio subprocesses."""
    servers = _stdio_servers()
    if not servers:
        return []

    checks: list[dict[str, Any]] = []
    need_node = any(_needs_node(cmd, args) for _, cmd, args in servers)
    need_uv = any(_needs_uv(cmd) for _, cmd, _ in servers)
    need_py = any(_needs_python(cmd) for _, cmd, _ in servers)

    if need_node:
        npx = shutil.which("npx")
        node = shutil.which("node")
        ok = bool(npx or node)
        checks.append(
            {
                "id": "mcp_node_runtime",
                "ok": ok,
                "label": "MCP stdio：Node.js / npx",
                "hint": (
                    None
                    if ok
                    else "远程 MCP 配置使用 npx/npm，但 PATH 中未找到 node/npx。"
                    "可安装 Node.js，或改用 HTTP MCP / 内置 web_search，或用 uvx 运行 Python MCP。"
                ),
            }
        )

    if need_uv:
        uv = shutil.which("uv") or shutil.which("uvx")
        checks.append(
            {
                "id": "mcp_uv_runtime",
                "ok": bool(uv),
                "label": "MCP stdio：uv / uvx",
                "hint": (
                    None
                    if uv
                    else "配置使用 uv/uvx 启动 MCP，但 PATH 中未找到。本项目用 uv 管理 Python，通常已可用。"
                ),
            }
        )

    if need_py:
        py = shutil.which("python") or shutil.which("python3") or shutil.which("py")
        checks.append(
            {
                "id": "mcp_python_runtime",
                "ok": bool(py),
                "label": "MCP stdio：python",
                "hint": None if py else "配置使用 python 启动 MCP，但 PATH 中未找到 Python。",
            }
        )

    merged = merge_mcp_server_blocks(_mcp_remote_blocks())
    http_count = sum(
        1
        for cfg in merged.values()
        if isinstance(cfg, dict) and str(cfg.get("url") or "").strip() and not str(cfg.get("command") or "").strip()
    )
    if http_count > 0:
        checks.append(
            {
                "id": "mcp_http_servers",
                "ok": True,
                "label": f"MCP HTTP/SSE 服务 ({http_count} 个，无需本机 npx)",
                "hint": "HTTP MCP 由独立进程提供，与 ly-next 同为 Python 项目无冲突。",
            }
        )

    return checks
