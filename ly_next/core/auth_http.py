from __future__ import annotations

from starlette.requests import Request
from starlette.websockets import WebSocket


def extract_api_key_from_request(
    request: Request,
    *,
    header_name: str,
    cookie_name: str,
    allow_query: bool,
) -> str | None:
    v = request.headers.get(header_name) or request.cookies.get(cookie_name)
    if v:
        return v
    if allow_query:
        return request.query_params.get("api_key")
    return None


def extract_api_key_from_websocket(
    websocket: WebSocket,
    *,
    header_name: str,
    cookie_name: str,
    allow_query: bool,
) -> str | None:
    v = websocket.headers.get(header_name) or websocket.cookies.get(cookie_name)
    if v:
        return v
    if allow_query:
        return websocket.query_params.get("api_key")
    return None
