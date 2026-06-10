"""Authenticated principal and RBAC role ordering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VALID_ROLES = frozenset({"viewer", "operator", "admin", "service"})
ROLE_RANK = {"viewer": 10, "operator": 20, "admin": 30, "service": 40}


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    role: str
    auth_method: str  # api_key | jwt

    def has_role(self, required: str) -> bool:
        need = str(required or "viewer").strip().lower()
        have = str(self.role or "viewer").strip().lower()
        if need not in ROLE_RANK or have not in ROLE_RANK:
            return False
        return ROLE_RANK[have] >= ROLE_RANK[need]


def normalize_role(raw: Any) -> str:
    role = str(raw or "viewer").strip().lower()
    return role if role in VALID_ROLES else "viewer"


def required_permission(method: str, path: str) -> str:
    """Minimum role for an authenticated API request."""
    m = (method or "GET").upper()
    p = path or ""

    if p.startswith("/api/system/settings"):
        return "admin"
    if p.startswith("/api/system/host-approvals") and m in ("POST", "PUT", "PATCH", "DELETE"):
        return "operator"
    if p.startswith("/api/system/") and m in ("POST", "PUT", "PATCH", "DELETE"):
        return "admin"
    if p.startswith("/api/tools/") and p.endswith("/call") and m == "POST":
        return "operator"
    if p in ("/api/chat",) or p.startswith("/api/chat/"):
        return "operator"
    if m in ("POST", "PUT", "PATCH", "DELETE"):
        return "operator"
    return "viewer"
