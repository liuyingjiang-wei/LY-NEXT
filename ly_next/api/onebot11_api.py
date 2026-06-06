from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ly_next.bridge.onebot11.call import normalize_action_name
from ly_next.bridge.onebot11.config import get_onebot11_settings
from ly_next.bridge.onebot11.manager import list_sessions
from ly_next.bridge.onebot11.napcat_actions import NAPCAT_ACTION_NAMES
from ly_next.bridge.onebot11.napcat_api import NapCatV11, is_bindable_action_name
from ly_next.bridge.onebot11.session import OneBotApiError
from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.core.thread_persistence import db_available, persistence_active, persistence_enabled

router = APIRouter(prefix="/onebot11", tags=["onebot11"])
logger = get_logger(__name__)


class OneBot11CallBody(BaseModel):
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    self_id: int | None = None
    timeout: float | None = Field(default=None, ge=1.0, le=300.0)


@router.get("/status")
async def onebot11_status():
    settings = get_onebot11_settings()
    host = str(config.get("server.host", "0.0.0.0") or "0.0.0.0").strip()
    napcat_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    port = int(config.get("server.port", 8000) or 8000)
    primary_path = settings.ws_paths[0] if settings.ws_paths else "/onebot/v11/ws"
    bound = sum(1 for n in NAPCAT_ACTION_NAMES if is_bindable_action_name(n))
    return {
        "enabled": settings.enabled,
        "ws_paths": list(settings.ws_paths),
        "napcat_ws_url": f"ws://{napcat_host}:{port}{primary_path}",
        "access_token_configured": bool(settings.access_token),
        "auto_reply_enabled": settings.auto_reply.enabled,
        "connected": [
            {"self_id": s.self_id, "nickname": s.nickname or ""}
            for s in list_sessions()
            if s.self_id
        ],
        "persistence": {
            "enabled": persistence_enabled(),
            "db_available": db_available(),
            "active": persistence_active(),
        },
        "actions_count": len(NAPCAT_ACTION_NAMES),
        "actions_bound_methods": bound,
    }


@router.get("/actions")
async def onebot11_actions():
    return {
        "count": len(NAPCAT_ACTION_NAMES),
        "actions": list(NAPCAT_ACTION_NAMES),
        "invoke_only": [n for n in NAPCAT_ACTION_NAMES if not is_bindable_action_name(n)],
    }


@router.get("/sessions")
async def onebot11_sessions():
    return {
        "sessions": [
            {"self_id": s.self_id, "nickname": s.nickname or ""}
            for s in list_sessions()
            if s.self_id
        ],
        "count": len(list_sessions()),
    }


@router.post("/call")
async def onebot11_call(body: OneBot11CallBody):
    if not get_onebot11_settings().enabled:
        raise HTTPException(status_code=503, detail="bridge.onebot11.enabled 为 false")
    try:
        name = normalize_action_name(body.action)
        api = NapCatV11(self_id=body.self_id, timeout=body.timeout)
        raw = await api.invoke_raw(name, body.params)
        return {"ok": True, "response": raw}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e)) from e
    except OneBotApiError as e:
        raise HTTPException(
            status_code=502,
            detail={"retcode": e.retcode, "message": str(e), "raw": e.raw},
        ) from e
    except Exception as e:
        logger.exception("[onebot11] HTTP call %s failed", body.action)
        raise HTTPException(status_code=500, detail=str(e)) from e
