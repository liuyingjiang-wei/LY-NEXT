"""MCP remote entry normalization and runtime catalog for workbench."""

from __future__ import annotations

import uuid
from typing import Any

from ly_next.core.config import config
from ly_next.mcp.remote_bridge import _block_to_obj, _slug, legacy_servers_to_blocks


def _new_entry_id() -> str:
    return f"e_{uuid.uuid4().hex[:12]}"


def slugs_from_body(body: Any) -> list[str]:
    obj = _block_to_obj(body)
    if not obj:
        return []
    m = obj.get("mcpServers")
    if not isinstance(m, dict) or isinstance(m, list):
        return []
    out: list[str] = []
    for k in m:
        slug = _slug(str(k))
        if slug:
            out.append(slug)
    return out


def _summary_for_cfg(cfg: dict[str, Any]) -> str:
    if not isinstance(cfg, dict):
        return ""
    cmd = str(cfg.get("command") or "").strip()
    if cmd:
        args = cfg.get("args")
        if isinstance(args, list) and args:
            return f"{cmd} {' '.join(str(a) for a in args[:4])}".strip()
        return cmd
    url = str(cfg.get("url") or "").strip()
    if url:
        transport = str(cfg.get("transport") or "http").strip()
        return f"{transport} {url}"
    return ""


def _label_from_body(body: Any, fallback: str = "MCP 配置") -> str:
    obj = _block_to_obj(body)
    if not obj:
        return fallback
    m = obj.get("mcpServers")
    if isinstance(m, dict) and not isinstance(m, list) and m:
        keys = list(m.keys())
        if len(keys) == 1:
            return str(keys[0])
        return f"{keys[0]} (+{len(keys) - 1})"
    return fallback


def normalize_remote_entries(remote: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return ``[{id, label, body}]`` from config (entries or legacy mcpServers)."""
    if not isinstance(remote, dict):
        return []

    entries_raw = remote.get("entries")
    if isinstance(entries_raw, list) and entries_raw:
        out: list[dict[str, Any]] = []
        for i, row in enumerate(entries_raw):
            if not isinstance(row, dict):
                continue
            body = row.get("body")
            if body is None and row.get("config"):
                body = row
            if body is None:
                continue
            eid = str(row.get("id") or "").strip() or _new_entry_id()
            label = str(row.get("label") or "").strip() or _label_from_body(body, f"配置块 {i + 1}")
            out.append({"id": eid, "label": label, "body": body})
        return out

    blocks: list[Any] = []
    ms = remote.get("mcpServers")
    if isinstance(ms, list):
        blocks = list(ms)
    if not blocks:
        legacy = config.get("tools.mcp.servers")
        if isinstance(legacy, list) and legacy:
            blocks = legacy_servers_to_blocks(legacy)

    out = []
    for i, raw in enumerate(blocks):
        obj = _block_to_obj(raw)
        if not obj:
            continue
        out.append(
            {
                "id": _new_entry_id(),
                "label": _label_from_body(raw, f"配置块 {i + 1}"),
                "body": raw if isinstance(raw, dict) else obj,
            }
        )
    return out


def entries_to_blocks(entries: list[dict[str, Any]]) -> list[Any]:
    blocks: list[Any] = []
    for row in entries or []:
        if not isinstance(row, dict):
            continue
        body = row.get("body")
        if body is None:
            continue
        blocks.append(body)
    return blocks


_loaded_mcp_slugs: set[str] = set()


def set_loaded_mcp_slugs(slugs: set[str] | list[str]) -> None:
    global _loaded_mcp_slugs
    _loaded_mcp_slugs = {str(s).strip() for s in slugs if str(s).strip()}


def get_loaded_mcp_slugs() -> frozenset[str]:
    return frozenset(_loaded_mcp_slugs)


def build_mcp_catalog_payload() -> dict[str, Any]:
    tools_root = config.get("tools") or {}
    mcp_cfg = tools_root.get("mcp") if isinstance(tools_root, dict) else {}
    if not isinstance(mcp_cfg, dict):
        mcp_cfg = {}
    remote = mcp_cfg.get("remote")
    remote_enabled = isinstance(remote, dict) and bool(remote.get("enabled"))
    entries = normalize_remote_entries(remote if isinstance(remote, dict) else None)
    loaded = get_loaded_mcp_slugs()
    use_prefix = bool(mcp_cfg.get("langgraph_tool_name_prefix", True))

    servers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        body = entry.get("body")
        obj = _block_to_obj(body)
        m = obj.get("mcpServers") if obj else None
        if not isinstance(m, dict) or isinstance(m, list):
            continue
        entry_label = str(entry.get("label") or "").strip()
        entry_id = str(entry.get("id") or "").strip()
        for raw_key, cfg in m.items():
            slug = _slug(str(raw_key))
            if not slug or slug in seen:
                continue
            seen.add(slug)
            label = entry_label if len(m) == 1 else f"{entry_label} · {raw_key}"
            summary = _summary_for_cfg(cfg if isinstance(cfg, dict) else {})
            servers.append(
                {
                    "slug": slug,
                    "label": label,
                    "entry_id": entry_id,
                    "loaded": slug in loaded,
                    "summary": summary,
                }
            )

    return {
        "remote_enabled": remote_enabled,
        "tool_name_prefix": use_prefix,
        "servers": servers,
    }


def parse_mcp_enabled_slugs(raw: Any) -> frozenset[str] | None:
    """``None`` = all MCP tools; empty frozenset = none; otherwise filter to listed slugs."""
    if raw is None:
        return None
    if not isinstance(raw, list):
        return None
    slugs = {_slug(str(x)) for x in raw if str(x).strip()}
    return frozenset(slugs)
