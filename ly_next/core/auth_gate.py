"""Central HTTP/WS authentication and RBAC checks."""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.websockets import WebSocket

from ly_next.core.auth_context import bind_principal, get_principal, release_principal
from ly_next.core.auth_http import extract_api_key_from_request, extract_api_key_from_websocket
from ly_next.core.auth_jwt import jwt_enabled, verify_access_token
from ly_next.core.auth_principal import Principal, normalize_role, required_permission
from ly_next.core.auth_users import authenticate_local_user, users_configured
from ly_next.core.config import config


def auth_mode() -> str:
    mode = str(config.get("auth.mode") or "api_key").strip().lower()
    return mode if mode in ("api_key", "jwt", "hybrid") else "api_key"


def rbac_enabled() -> bool:
    return auth_mode() in ("jwt", "hybrid") and users_configured()


def _jwt_cookie_name() -> str:
    jc = config.get("auth.jwt") or {}
    if isinstance(jc, dict) and jc.get("cookie_name"):
        return str(jc["cookie_name"])
    return "ly_session"


def _extract_bearer_token(request: Request | WebSocket) -> str | None:
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not header:
        return None
    text = str(header).strip()
    if not text.lower().startswith("bearer "):
        return None
    token = text[7:].strip()
    return token or None


def _principal_from_jwt(token: str) -> Principal | None:
    payload = verify_access_token(token)
    if not payload:
        return None
    return Principal(
        subject=str(payload.get("sub") or ""),
        role=normalize_role(payload.get("role")),
        auth_method="jwt",
    )


def _principal_from_api_key(key: str) -> Principal | None:
    expected = str(config.get("auth.api_key") or "").strip()
    if not expected or key != expected:
        return None
    return Principal(subject="api_key", role="service", auth_method="api_key")


def authenticate_http(request: Request) -> Principal | None:
    mode = auth_mode()
    header_name = config.get("auth.header_name", "X-API-Key")
    cookie_name = config.get("auth.cookie_name", "ly_api_key")
    allow_query = bool(config.get("auth.allow_api_key_in_query", False))

    if mode in ("jwt", "hybrid") and jwt_enabled():
        bearer = _extract_bearer_token(request)
        if bearer:
            principal = _principal_from_jwt(bearer)
            if principal:
                return principal
        session = request.cookies.get(_jwt_cookie_name())
        if session:
            principal = _principal_from_jwt(session)
            if principal:
                return principal

    if mode == "jwt":
        return None

    provided = extract_api_key_from_request(
        request,
        header_name=header_name,
        cookie_name=cookie_name,
        allow_query=allow_query,
    )
    if provided:
        return _principal_from_api_key(provided)
    return None


def authenticate_websocket(websocket: WebSocket) -> Principal | None:
    mode = auth_mode()
    header_name = config.get("auth.header_name", "X-API-Key")
    cookie_name = config.get("auth.cookie_name", "ly_api_key")
    allow_query = bool(config.get("auth.allow_api_key_in_query", False))

    if mode in ("jwt", "hybrid") and jwt_enabled():
        bearer = _extract_bearer_token(websocket)
        if bearer:
            principal = _principal_from_jwt(bearer)
            if principal:
                return principal
        session = websocket.cookies.get(_jwt_cookie_name())
        if session:
            principal = _principal_from_jwt(session)
            if principal:
                return principal

    if mode == "jwt":
        return None

    provided = extract_api_key_from_websocket(
        websocket,
        header_name=header_name,
        cookie_name=cookie_name,
        allow_query=allow_query,
    )
    if provided:
        return _principal_from_api_key(provided)
    return None


def authorize_http(principal: Principal, request: Request) -> tuple[bool, str | None]:
    if not rbac_enabled():
        return True, None
    need = required_permission(request.method, request.url.path)
    if principal.has_role(need):
        return True, None
    return False, f"requires role {need}"


def login_with_password(username: str, password: str) -> Principal | None:
    user = authenticate_local_user(username, password)
    if not user:
        return None
    return Principal(subject=user.username, role=normalize_role(user.role), auth_method="jwt")


def principal_from_request_state(request: Request) -> Principal | None:
    p = getattr(request.state, "principal", None)
    if isinstance(p, Principal):
        return p
    return get_principal()


def principal_summary() -> dict[str, Any] | None:
    p = get_principal()
    if not p:
        return None
    return {"subject": p.subject, "role": p.role, "auth_method": p.auth_method}
