from __future__ import annotations

from urllib.parse import parse_qs

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ly_next.bridge.onebot11.config import get_onebot11_settings
from ly_next.bridge.onebot11.session import OneBotSession
from ly_next.core.logger import get_logger

logger = get_logger(__name__)

_registered_paths: set[str] = set()


def _extract_access_token(websocket: WebSocket) -> str:
    auth = websocket.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    q = parse_qs(websocket.url.query or "")
    for key in ("access_token", "token"):
        vals = q.get(key)
        if vals and str(vals[0]).strip():
            return str(vals[0]).strip()
    return ""


async def _onebot_ws_auth_ok(websocket: WebSocket) -> bool:
    settings = get_onebot11_settings()
    expected = settings.access_token
    if not expected:
        return True
    provided = _extract_access_token(websocket)
    if provided == expected:
        return True
    if websocket.client_state != WebSocketState.CONNECTED:
        await websocket.accept()
    await websocket.close(code=1008, reason="invalid access_token")
    return False


async def serve_onebot_websocket(websocket: WebSocket) -> None:
    settings = get_onebot11_settings()
    path = websocket.url.path
    if not settings.enabled:
        logger.warning("[onebot11] rejected %s: bridge.onebot11.enabled is false", path)
        await websocket.accept()
        await websocket.close(code=1008, reason="onebot11 disabled")
        return
    if not await _onebot_ws_auth_ok(websocket):
        return

    logger.info("[onebot11] NapCat connected path=%s", path)
    await websocket.accept()
    session = OneBotSession(websocket)
    await session.start()

    try:
        if session._recv_task is not None:
            await session._recv_task
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("[onebot11] ws ended: %s", e, exc_info=True)
    finally:
        await session.close()


def attach_onebot_routes(*routers: APIRouter) -> list[str]:
    settings = get_onebot11_settings()
    paths: list[str] = []

    def _register(path: str, router: APIRouter) -> None:
        norm = path if path.startswith("/") else f"/{path}"
        if norm in _registered_paths:
            return

        @router.websocket(norm)
        async def onebot_v11_ws(websocket: WebSocket) -> None:
            await serve_onebot_websocket(websocket)

        _registered_paths.add(norm)
        paths.append(norm)

    for path in settings.ws_paths:
        for router in routers:
            _register(path, router)
    return paths
