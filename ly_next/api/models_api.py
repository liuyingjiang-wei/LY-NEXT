"""REST API for registered LLM models (ly-ask style)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ly_next.agent.llm_text import text_from_chat_response
from ly_next.agent.vision_precaption import _extract_assistant_text
from ly_next.core.config import config
from ly_next.models.factory import LLMFactory
from ly_next.models.registry import MODEL_FORMATS, ModelRegistry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/models", tags=["models"])


class ModelAddRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    format: str = "openai"
    api_key: str = ""
    base_url: str = ""
    model: str = Field(..., min_length=1)
    auth_mode: str | None = None
    auth_header_name: str | None = None
    token_field: str | None = None


class SetActiveRequest(BaseModel):
    name: str = Field(..., min_length=1)


class ModelTestRequest(BaseModel):
    name: str | None = None
    message: str = "Reply with exactly: OK"


def _reply_snippet(resp: Any) -> str:
    if not isinstance(resp, dict):
        return str(resp or "").strip()[:120]
    text = text_from_chat_response(resp)
    if not text:
        text = _extract_assistant_text(resp)
    text = (text or "").strip()
    if len(text) > 120:
        return text[:119] + "…"
    return text or "(空回复)"


@router.get("")
async def list_models():
    ModelRegistry.ensure_loaded()
    models = ModelRegistry.list_model_infos()
    default = ModelRegistry.default_name()
    return {
        "models": models,
        "formats": sorted(MODEL_FORMATS),
        "default_model": default,
        "active_provider": default,
        "request_timeout": int(config.get("llm.request_timeout", 60) or 60),
    }


@router.get("/{name}")
async def get_model_detail(name: str):
    try:
        detail = ModelRegistry.entry_for_edit(name)
        detail["ok"] = True
        return detail
    except ValueError as e:
        return {"ok": False, "error": str(e)}


@router.post("/active")
async def set_active_model(req: SetActiveRequest):
    try:
        ModelRegistry.set_default_name(req.name.strip())
        config.load()
        ModelRegistry.reload()
        return {"ok": True, "message": f"已切换默认模型为「{req.name}」，立即生效"}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


@router.post("/test")
async def test_model(req: ModelTestRequest):
    import time

    ModelRegistry.ensure_loaded()
    name = (req.name or ModelRegistry.default_name()).strip()
    try:
        entry = ModelRegistry.get_entry(name)
        if not entry:
            return {"ok": False, "error": f"模型 '{name}' 未注册"}
        t0 = time.perf_counter()
        client = LLMFactory.create_client(registry_name=name)
        resp = await client.chat_complete(
            [{"role": "user", "content": req.message}],
            temperature=0,
            max_tokens=64,
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        close_fn = getattr(client, "close", None)
        if callable(close_fn):
            try:
                await close_fn()
            except Exception:
                pass
        return {
            "ok": True,
            "name": name,
            "format": entry.get("format"),
            "model": entry.get("model"),
            "latency_ms": latency_ms,
            "reply": _reply_snippet(resp),
        }
    except Exception as e:
        logger.exception("model test failed")
        return {"ok": False, "error": str(e)}


@router.post("/add")
async def add_model(req: ModelAddRequest):
    fmt = req.format.strip().lower()
    if fmt == "openai-compatible":
        fmt = "openai_compat"
    if fmt not in MODEL_FORMATS:
        return {"ok": False, "error": f"不支持的格式: {req.format}"}

    name = req.name.strip()
    is_update = name in ModelRegistry.list_names()

    if not is_update and not req.api_key.strip() and fmt not in ("ollama",):
        if fmt != "openai_compat" or not req.base_url.strip():
            return {"ok": False, "error": "API Key 不能为空"}

    extra: dict[str, Any] = {}
    if req.auth_mode:
        extra["auth_mode"] = req.auth_mode.strip()
    if req.auth_header_name:
        extra["auth_header_name"] = req.auth_header_name.strip()
    if req.token_field:
        extra["token_field"] = req.token_field.strip()

    try:
        merged = ModelRegistry.merge_update(
            name,
            format=fmt,
            api_key=req.api_key,
            base_url=req.base_url,
            model=req.model,
            extra=extra or None,
        )
        ModelRegistry.upsert(merged, save=True)
        config.load()
        ModelRegistry.reload()
        verb = "更新" if is_update else "添加"
        return {"ok": True, "message": f"模型「{name}」已{verb}并立即生效"}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.exception("add/update model failed")
        return {"ok": False, "error": str(e)}


@router.delete("/{name}")
async def delete_model(name: str):
    try:
        ModelRegistry.remove(name.strip(), save=True)
        config.load()
        ModelRegistry.reload()
        return {"ok": True, "message": f"已删除模型「{name}」"}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.exception("remove model failed")
        return {"ok": False, "error": str(e)}
