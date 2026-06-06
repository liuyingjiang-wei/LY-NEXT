"""Image generation via OpenAI-compatible /images/generations API only."""

from __future__ import annotations

from typing import Any

import httpx

from ly_next.core.config import config
from ly_next.core.http_url import ensure_http_base
from ly_next.models.openai_compat_auth import openai_compat_auth_headers, require_remote_api_key

GEN_PROVIDER_ID = "openai_compat"


def image_cfg() -> dict[str, Any]:
    raw = config.get("tools.image") or {}
    return raw if isinstance(raw, dict) else {}


_IMAGE_GEN_OVERRIDE_KEYS = frozenset(
    {"model", "size", "quality", "api_key", "base_url", "auth_mode", "auth_header_name"}
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


async def generate_openai_compat_image(prompt: str) -> str:
    block = _resolve_image_block()
    api_key = str(block.get("api_key") or "").strip()
    base = ensure_http_base(str(block.get("base_url") or "https://api.openai.com/v1"))
    require_remote_api_key(
        api_key,
        base,
        auth_mode=block.get("auth_mode"),
        auth_header_name=block.get("auth_header_name"),
    )
    model = str(block.get("model") or "gpt-image-1").strip()
    size = str(block.get("size") or "1024x1024").strip()
    url = f"{base.rstrip('/')}/images/generations"
    headers = openai_compat_auth_headers(
        api_key,
        auth_mode=block.get("auth_mode"),
        auth_header_name=block.get("auth_header_name"),
    )
    headers["Content-Type"] = "application/json"
    body: dict[str, Any] = {"model": model, "prompt": prompt, "n": 1, "size": size}
    q = block.get("quality")
    if q:
        body["quality"] = q
    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.post(url, headers=headers, json=body)
        r.raise_for_status()
        data = r.json()
    items = data.get("data") or []
    if not items:
        raise RuntimeError(f"生图无 data: {data}")
    first = items[0] if isinstance(items[0], dict) else {}
    if first.get("url"):
        return str(first["url"])
    b64 = first.get("b64_json")
    if b64:
        return f"data:image/png;base64,{b64}"
    raise RuntimeError("生图响应缺少 url / b64_json")


async def generate_with_provider(prompt: str, provider: str | None = None) -> str:
    pid = (provider or str(image_cfg().get("provider") or GEN_PROVIDER_ID)).strip().lower()
    if pid not in (GEN_PROVIDER_ID, "openai_compat", "openai-compatible", "compat"):
        raise ValueError(f"仅支持 OpenAI 兼容生图 ({GEN_PROVIDER_ID})，当前: {pid}")
    return await generate_openai_compat_image(prompt)
