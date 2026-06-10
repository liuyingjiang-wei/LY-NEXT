"""JWT login and session introspection."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ly_next.core.audit_log import audit_auth_event
from ly_next.core.auth_context import bind_principal, get_principal, release_principal
from ly_next.core.auth_gate import (
    auth_mode,
    login_with_password,
    principal_from_request_state,
    rbac_enabled,
)
from ly_next.core.auth_jwt import issue_access_token, jwt_enabled
from ly_next.core.auth_users import users_configured
from ly_next.core.config import config

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


@router.post("/auth/login")
async def auth_login(body: LoginRequest) -> dict[str, Any]:
    if not jwt_enabled() or not users_configured():
        raise HTTPException(
            status_code=503,
            detail="JWT login is not configured (set auth.mode and auth.users)",
        )
    principal = login_with_password(body.username, body.password)
    if not principal:
        audit_auth_event("login_failed", username=body.username)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token, ttl = issue_access_token(username=principal.subject, role=principal.role)
    audit_auth_event("login_success", username=principal.subject, role=principal.role)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": ttl,
        "role": principal.role,
        "subject": principal.subject,
    }


@router.get("/auth/me")
async def auth_me(request: Request) -> dict[str, Any]:
    principal = principal_from_request_state(request)
    if not principal:
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = bind_principal(principal)
    try:
        p = get_principal()
        body = {"authenticated": True}
        if p:
            body.update({"subject": p.subject, "role": p.role, "auth_method": p.auth_method})
        return body
    finally:
        release_principal(token)


@router.get("/auth/config")
async def auth_config() -> dict[str, Any]:
    return {
        "mode": auth_mode(),
        "rbac_enabled": rbac_enabled(),
        "jwt_enabled": jwt_enabled(),
        "users_configured": users_configured(),
        "cookie_name": str((config.get("auth.jwt") or {}).get("cookie_name") or "ly_session"),
    }
