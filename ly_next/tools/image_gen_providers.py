"""Image generation via OpenAI-compatible /images/generations API only."""

from __future__ import annotations

from typing import Any

import httpx

from ly_next.core.config import config
from ly_next.core.http_url import ensure_http_base
from ly_next.core.logger import get_logger
from ly_next.models.openai_compat_auth import openai_compat_auth_headers, require_remote_api_key
from ly_next.tools.image_prompt import build_image_generation_input

logger = get_logger(__name__)

GEN_PROVIDER_ID = "openai_compat"


def image_cfg() -> dict[str, Any]:
    raw = config.get("tools.image") or {}
    return raw if isinstance(raw, dict) else {}


_IMAGE_GEN_OVERRIDE_KEYS = frozenset(
    {
        "model",
        "size",
        "quality",
        "api_key",
        "base_url",
        "auth_mode",
        "auth_header_name",
        "negative_prompt",
        "negative_prompt_mode",
    }
)


def _resolve_image_block() -> dict[str, Any]:
    """Merge ``tools.image`` overrides onto ``config_ref`` LLM block."""
    cfg = image_cfg()
    ref = str(
        cfg.get("config_ref") or cfg.get("openai_compat_config_ref") or "openai_compat_llm"
    ).strip()
    block: dict[str, Any] = {}
    ref_block = config.get(ref) or {}
    if isinstance(ref_block, dict):
        block.update(ref_block)
    for k in _IMAGE_GEN_OVERRIDE_KEYS:
        v = cfg.get(k)
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        block[k] = v
    return block


def _request_timeout_seconds() -> float:
    raw = image_cfg().get("request_timeout_seconds", 120)
    try:
        sec = float(raw)
    except (TypeError, ValueError):
        sec = 120.0
    return max(15.0, min(sec, 300.0))


def _format_http_error(exc: BaseException, *, timeout_sec: float) -> str:
    msg = str(exc).strip()
    if msg:
        return msg
    if isinstance(exc, httpx.TimeoutException):
        return (
            f"生图请求超时（{int(timeout_sec)}s）。"
            "请缩短 prompt、调大 tools.image.request_timeout_seconds，或检查生图 API 是否可用。"
        )
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code if exc.response is not None else "?"
        body = ""
        try:
            if exc.response is not None:
                body = (exc.response.text or "")[:240].strip()
        except Exception:
            pass
        if body:
            return f"生图 API HTTP {code}: {body}"
        return f"生图 API HTTP {code}"
    name = type(exc).__name__
    return name or "生图失败"


async def generate_openai_compat_image(
    prompt: str,
    *,
    negative_prompt: str | None = None,
) -> tuple[str, bool, str | None]:
    """Return (image_url_or_data, prompt_was_truncated, size_used)."""
    block = _resolve_image_block()
    config_size = str(block.get("size") or "").strip()
    built = build_image_generation_input(
        prompt,
        negative_override=negative_prompt,
        config_size=config_size or None,
    )
    if not built.prompt:
        raise ValueError("prompt 不能为空")

    api_key = str(block.get("api_key") or "").strip()
    base = ensure_http_base(block.get("base_url"), default="https://api.openai.com/v1")
    require_remote_api_key(
        api_key,
        base,
        auth_mode=block.get("auth_mode"),
        auth_header_name=block.get("auth_header_name"),
    )
    model = str(block.get("model") or "gpt-image-1").strip()
    url = f"{base.rstrip('/')}/images/generations"
    headers = openai_compat_auth_headers(
        api_key,
        auth_mode=block.get("auth_mode"),
        auth_header_name=block.get("auth_header_name"),
    )
    headers["Content-Type"] = "application/json"
    body: dict[str, Any] = {"model": model, "prompt": built.prompt, "n": 1}
    if built.size:
        body["size"] = built.size
    if built.negative_prompt_field:
        body["negative_prompt"] = built.negative_prompt_field
    q = block.get("quality")
    if q:
        body["quality"] = q
    timeout_sec = _request_timeout_seconds()
    timeout = httpx.Timeout(timeout_sec, connect=15.0)
    size_label = built.size or "auto"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        detail = _format_http_error(e, timeout_sec=timeout_sec)
        logger.warning(
            "[generate_image] API error model=%s size=%s(%s) prompt_len=%s: %s",
            model,
            size_label,
            built.size_source,
            len(built.prompt),
            detail,
        )
        raise RuntimeError(detail) from e

    items = data.get("data") or []
    if not items:
        raise RuntimeError(f"生图无 data: {data}")
    first = items[0] if isinstance(items[0], dict) else {}
    if first.get("url"):
        return str(first["url"]), built.truncated, built.size
    b64 = first.get("b64_json")
    if b64:
        return f"data:image/png;base64,{b64}", built.truncated, built.size
    raise RuntimeError("生图响应缺少 url / b64_json")


async def generate_with_provider(prompt: str, provider: str | None = None) -> str:
    pid = (provider or str(image_cfg().get("provider") or GEN_PROVIDER_ID)).strip().lower()
    if pid not in (GEN_PROVIDER_ID, "openai_compat", "openai-compatible", "compat"):
        raise ValueError(f"仅支持 OpenAI 兼容生图 ({GEN_PROVIDER_ID})，当前: {pid}")
    url, _, _ = await generate_openai_compat_image(prompt)
    return url
