"""Preflight validation for a single MCP remote config block."""

from __future__ import annotations

import json
import shutil
from typing import Any
from urllib.parse import urlparse

import httpx

from ly_next.mcp.preflight import _needs_node, _needs_python, _needs_uv


def _servers_from_body(body: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(body, dict):
        return {}
    cfg = body.get("config") if isinstance(body.get("config"), dict) else body
    if not isinstance(cfg, dict):
        return {}
    servers = cfg.get("mcpServers")
    if isinstance(servers, dict):
        return {str(k): v for k, v in servers.items() if isinstance(v, dict)}
    return {}


def validate_mcp_block_body(body: Any) -> tuple[dict[str, dict[str, Any]], list[str]]:
    errors: list[str] = []
    if body is None:
        return {}, ["配置体为空"]
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError as exc:
            return {}, [f"JSON 无效: {exc}"]
    if not isinstance(body, dict):
        return {}, ["配置体必须是 JSON 对象"]

    servers = _servers_from_body(body)
    if not servers:
        errors.append("未找到 mcpServers（需 config.mcpServers 或顶层 mcpServers）")
        return {}, errors

    for name, srv in servers.items():
        cmd = str(srv.get("command") or "").strip()
        url = str(srv.get("url") or "").strip()
        if not cmd and not url:
            errors.append(f"「{name}」需填写 command（stdio）或 url（HTTP）")
        if url:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                errors.append(f"「{name}」url 须为 http/https")
    return servers, errors


def runtime_checks_for_servers(servers: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    need_node = False
    need_uv = False
    need_py = False
    http_urls: list[tuple[str, str]] = []

    for name, srv in servers.items():
        cmd = str(srv.get("command") or "").strip()
        args = srv.get("args")
        arg_list = [str(x) for x in args] if isinstance(args, list) else []
        url = str(srv.get("url") or "").strip()
        if cmd:
            need_node = need_node or _needs_node(cmd, arg_list)
            need_uv = need_uv or _needs_uv(cmd)
            need_py = need_py or _needs_python(cmd)
            checks.append(
                {
                    "id": f"stdio:{name}",
                    "ok": True,
                    "label": f"{name}（stdio: {cmd}）",
                    "hint": "保存后首次对话才会拉起子进程",
                }
            )
        elif url:
            http_urls.append((name, url))
            checks.append(
                {
                    "id": f"http:{name}",
                    "ok": True,
                    "label": f"{name}（HTTP）",
                    "hint": url,
                }
            )

    if need_node:
        ok = bool(shutil.which("npx") or shutil.which("node"))
        checks.insert(
            0,
            {
                "id": "runtime_node",
                "ok": ok,
                "label": "Node.js / npx",
                "hint": None if ok else "PATH 中未找到 node/npx，stdio MCP 可能无法启动",
            },
        )
    if need_uv:
        ok = bool(shutil.which("uv") or shutil.which("uvx"))
        checks.insert(
            0,
            {
                "id": "runtime_uv",
                "ok": ok,
                "label": "uv / uvx",
                "hint": None if ok else "PATH 中未找到 uv/uvx",
            },
        )
    if need_py:
        ok = bool(shutil.which("python") or shutil.which("python3") or shutil.which("py"))
        checks.insert(
            0,
            {
                "id": "runtime_python",
                "ok": ok,
                "label": "Python",
                "hint": None if ok else "PATH 中未找到 python",
            },
        )

    return checks, http_urls


async def probe_http_mcp(url: str, *, timeout_sec: float = 4.0) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return {"ok": False, "error": "仅支持 http/https URL"}
    try:
        async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=True) as client:
            for method in ("GET", "HEAD"):
                try:
                    resp = await client.request(method, url)
                    return {
                        "ok": resp.status_code < 500,
                        "status_code": resp.status_code,
                        "method": method,
                        "hint": None
                        if resp.status_code < 500
                        else f"HTTP {resp.status_code}，请确认 MCP 服务已启动且路径正确",
                    }
                except httpx.HTTPError:
                    continue
            return {"ok": False, "error": "无法连接（连接被拒绝或超时）"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def preflight_mcp_block(body: Any, *, probe_http: bool = True) -> dict[str, Any]:
    servers, errors = validate_mcp_block_body(body)
    if errors:
        return {"ok": False, "errors": errors, "checks": [], "http_probes": []}

    checks, http_urls = runtime_checks_for_servers(servers)
    runtime_ok = all(c.get("ok", True) for c in checks if c["id"].startswith("runtime_"))

    http_probes: list[dict[str, Any]] = []
    if probe_http and http_urls:
        for name, url in http_urls:
            probe = await probe_http_mcp(url)
            http_probes.append({"name": name, "url": url, **probe})
            checks.append(
                {
                    "id": f"probe:{name}",
                    "ok": bool(probe.get("ok")),
                    "label": f"{name} 连通性",
                    "hint": probe.get("hint")
                    or probe.get("error")
                    or f"HTTP {probe.get('status_code', '—')}",
                }
            )

    all_ok = runtime_ok and all(p.get("ok") for p in http_probes) if http_probes else runtime_ok
    return {
        "ok": all_ok and not errors,
        "errors": errors,
        "checks": checks,
        "http_probes": http_probes,
        "server_count": len(servers),
    }
