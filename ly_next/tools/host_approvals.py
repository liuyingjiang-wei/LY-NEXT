"""Approval gate for destructive host tool actions."""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from ly_next.core.config import config
from ly_next.tools.base import ToolResult

ApprovalStatus = Literal["pending", "approved", "denied", "expired", "consumed"]


@dataclass
class HostApproval:
    id: str
    tool: str
    action: str
    summary: str
    payload: dict[str, Any]
    status: ApprovalStatus = "pending"
    created_at: float = field(default_factory=time.time)
    decided_at: float | None = None


_store: dict[str, HostApproval] = {}


def _approvals_cfg() -> dict[str, Any]:
    host = config.get("tools.host", {}) or {}
    if not isinstance(host, dict):
        return {}
    raw = host.get("approvals", {}) or {}
    return raw if isinstance(raw, dict) else {}


def approvals_enabled() -> bool:
    return bool(_approvals_cfg().get("enabled", True))


def approval_ttl_seconds() -> int:
    try:
        return max(60, min(int(_approvals_cfg().get("ttl_seconds", 600) or 600), 86400))
    except (TypeError, ValueError):
        return 600


def _purge_expired() -> None:
    ttl = approval_ttl_seconds()
    now = time.time()
    for _aid, item in list(_store.items()):
        if item.status == "pending" and now - item.created_at > ttl:
            item.status = "expired"
            item.decided_at = now


def list_approvals(*, status: ApprovalStatus | None = None) -> list[dict[str, Any]]:
    _purge_expired()
    out: list[dict[str, Any]] = []
    for item in sorted(_store.values(), key=lambda x: x.created_at, reverse=True):
        if status and item.status != status:
            continue
        out.append(_approval_dict(item))
    return out


def _approval_dict(item: HostApproval) -> dict[str, Any]:
    return {
        "id": item.id,
        "tool": item.tool,
        "action": item.action,
        "summary": item.summary,
        "status": item.status,
        "created_at": item.created_at,
        "decided_at": item.decided_at,
        "payload": item.payload,
    }


def get_approval(approval_id: str) -> HostApproval | None:
    _purge_expired()
    return _store.get(str(approval_id or "").strip())


def create_approval(
    *,
    tool: str,
    action: str,
    summary: str,
    payload: dict[str, Any],
) -> HostApproval:
    _purge_expired()
    item = HostApproval(
        id=uuid.uuid4().hex,
        tool=tool,
        action=action,
        summary=summary,
        payload=dict(payload),
    )
    _store[item.id] = item
    return item


def decide_approval(approval_id: str, *, approve: bool) -> tuple[HostApproval | None, str | None]:
    _purge_expired()
    item = get_approval(approval_id)
    if item is None:
        return None, "approval not found"
    if item.status != "pending":
        return item, f"approval already {item.status}"
    item.status = "approved" if approve else "denied"
    item.decided_at = time.time()
    return item, None


def consume_approval(approval_id: str, *, tool: str, action: str) -> tuple[bool, str | None]:
    item = get_approval(approval_id)
    if item is None:
        return False, "approval not found or expired"
    if item.status == "expired":
        return False, "approval expired"
    if item.status == "denied":
        return False, "approval was denied"
    if item.status == "consumed":
        return False, "approval already used"
    if item.status != "approved":
        return False, "approval still pending; approve via API or workbench first"
    if item.tool != tool or item.action != action:
        return False, "approval does not match this tool action"
    item.status = "consumed"
    item.decided_at = item.decided_at or time.time()
    return True, None


def approval_required_result(item: HostApproval) -> ToolResult:
    return ToolResult(
        success=False,
        error=(
            f"Approval required for {item.action}. "
            f"Ask the user to approve id={item.id}, then retry with approval_token."
        ),
        result={
            "approval_required": True,
            "approval_id": item.id,
            "action": item.action,
            "summary": item.summary,
            "approve_api": f"/api/system/host-approvals/{item.id}/approve",
            "deny_api": f"/api/system/host-approvals/{item.id}/deny",
        },
    )


def check_approval_gate(
    *,
    tool: str,
    action: str,
    summary: str,
    payload: dict[str, Any],
    approval_token: str | None,
    needs_approval: bool,
) -> ToolResult | None:
    """Return ToolResult to short-circuit, or None if execution may proceed."""
    if not needs_approval:
        return None
    if not approvals_enabled():
        return None

    token = str(approval_token or "").strip()
    if token:
        ok, err = consume_approval(token, tool=tool, action=action)
        if ok:
            return None
        return ToolResult(success=False, error=err or "invalid approval")

    item = create_approval(tool=tool, action=action, summary=summary, payload=payload)
    return approval_required_result(item)


_DEFAULT_EXEC_PATTERNS = [
    r"\brm\s+(-[^\s]*\s+)*-r",
    r"\brm\s+-rf\b",
    r"\brm\s+",
    r"\bdel\s+/[fq]",
    r"\bRemove-Item\b",
    r"\brmdir\s+/s",
    r"\bformat\s+",
    r"\bmkfs\b",
    r"\bshred\b",
    r"\btruncate\s+-s\s+0\b",
    r":\s*>\s*/",
]


def _exec_patterns() -> list[re.Pattern[str]]:
    raw = _approvals_cfg().get("exec_patterns")
    patterns = list(_DEFAULT_EXEC_PATTERNS)
    if isinstance(raw, list):
        for item in raw:
            text = str(item or "").strip()
            if text:
                patterns.append(text)
    out: list[re.Pattern[str]] = []
    for p in patterns:
        try:
            out.append(re.compile(p, re.IGNORECASE))
        except re.error:
            continue
    return out


def command_needs_approval(command: str) -> bool:
    if not approvals_enabled():
        return False
    mode = str(_approvals_cfg().get("mode", "destructive") or "destructive").strip().lower()
    if mode == "off":
        return False
    if mode == "always":
        return True
    text = str(command or "")
    return any(pat.search(text) for pat in _exec_patterns())


def delete_needs_approval(*, recursive: bool) -> bool:
    if not approvals_enabled():
        return False
    cfg = _approvals_cfg()
    if recursive and bool(cfg.get("require_for_recursive_delete", True)):
        return True
    return bool(cfg.get("require_for_delete", True))
