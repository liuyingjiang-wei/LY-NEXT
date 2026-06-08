from __future__ import annotations

import contextlib
import copy
import re
import time
from typing import Any

from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.models.factory import LLMFactory

logger = get_logger(__name__)

_IMAGE_TYPES = frozenset({"image", "image_url", "input_image"})
_SUPPORTED_PROVIDERS = frozenset({"openai", "openai_compat"})


def _user_has_image_parts(msg: dict[str, Any]) -> bool:
    c = msg.get("content")
    if not isinstance(c, list):
        return False
    for p in c:
        if not isinstance(p, dict):
            continue
        if str(p.get("type", "")).lower() in _IMAGE_TYPES:
            return True
    return False


def _split_user_multimodal(content: list[Any]) -> tuple[str, list[dict[str, Any]]]:
    texts: list[str] = []
    images: list[dict[str, Any]] = []
    for p in content:
        if not isinstance(p, dict):
            continue
        t = str(p.get("type", "")).lower()
        if t == "text":
            tx = p.get("text")
            if isinstance(tx, str) and tx.strip():
                texts.append(tx.strip())
        elif t in _IMAGE_TYPES:
            images.append(p)
    return "\n".join(texts).strip(), images


def _extract_assistant_text(resp: dict[str, Any] | Any) -> str:
    if not isinstance(resp, dict):
        return str(resp or "").strip()
    choices = resp.get("choices")
    if isinstance(choices, list) and choices:
        ch0 = choices[0]
        if isinstance(ch0, dict):
            msg = ch0.get("message") or ch0
            if isinstance(msg, dict):
                c = msg.get("content")
                if isinstance(c, str):
                    return c.strip()
                if isinstance(c, list):
                    parts: list[str] = []
                    for block in c:
                        if isinstance(block, dict) and str(block.get("type", "")).lower() == "text":
                            tx = block.get("text")
                            if isinstance(tx, str):
                                parts.append(tx)
                    return "\n".join(parts).strip()
    msg = resp.get("message")
    if isinstance(msg, dict):
        c = msg.get("content")
        if isinstance(c, str):
            return c.strip()
    return ""


def _sanitize_merged_text(s: str, max_chars: int) -> str:
    if not isinstance(s, str):
        s = str(s)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)
    s = s.strip()
    if max_chars > 0 and len(s) > max_chars:
        s = s[: max_chars - 1] + "…"
    return s


def _resolve_precaption_model() -> tuple[str, str, str]:
    """Return (registry_name, format, model_id)."""
    cfg = config.get("agent.vision_precaption", {}) or {}
    if not isinstance(cfg, dict):
        cfg = {}

    from ly_next.models.registry import ModelRegistry

    ModelRegistry.ensure_loaded()

    model_name = str(cfg.get("model_name") or "").strip()
    if model_name:
        entry = ModelRegistry.get_entry(model_name)
        if entry:
            fmt = str(entry.get("format") or "openai").strip().lower()
            model_id = str(entry.get("model") or "").strip()
            return model_name, fmt, model_id

    prov = str(cfg.get("provider") or "openai").strip().lower()
    model = str(cfg.get("model") or "").strip()

    entry = ModelRegistry.get_entry(prov)
    if entry:
        fmt = str(entry.get("format") or prov).strip().lower()
        if not model and entry.get("model"):
            model = str(entry.get("model")).strip()
        return prov, fmt, model

    if not model:
        block = config.get(f"{prov}_llm", {}) or {}
        if isinstance(block, dict) and block.get("model"):
            model = str(block.get("model")).strip()

    return prov, prov, model


def _failure_strategy(raw: dict[str, Any]) -> str:
    s = str(raw.get("on_failure") or "keep_original").strip().lower()
    if s in ("annotate", "text_only", "keep_original"):
        return s
    return "keep_original"


def _failure_note_text(raw: dict[str, Any]) -> str:
    default = "（图像预识别暂不可用，请仅根据用户文字与常识作答；用户曾附带图片。）"
    fn = raw.get("failure_note")
    if isinstance(fn, str) and fn.strip():
        return fn.strip()
    return default


def _apply_precaption_failure(
    messages: list[dict[str, Any]],
    idx: int,
    user_text: str,
    *,
    raw: dict[str, Any],
    prefix: str,
    max_merged_chars: int,
    exc: BaseException,
) -> list[dict[str, Any]]:
    strategy = _failure_strategy(raw)
    logger.info(
        "[vision_precaption] degraded strategy=%s idx=%s err_type=%s err=%s",
        strategy,
        idx,
        type(exc).__name__,
        exc,
    )
    if strategy == "keep_original":
        return messages
    out = copy.deepcopy(messages)
    if strategy == "text_only":
        merged = _sanitize_merged_text(user_text, max_merged_chars)
    else:
        note = _failure_note_text(raw)
        merged = _sanitize_merged_text(
            "\n\n".join(x for x in (user_text, f"{prefix}{note}") if x).strip(),
            max_merged_chars,
        )
    out[idx] = {**out[idx], "content": merged}
    return out


def messages_need_vision_precaption(
    messages: list[dict[str, Any]], *, skip_precaption: bool = False
) -> bool:
    raw = config.get("agent.vision_precaption", {}) or {}
    if skip_precaption or not isinstance(raw, dict) or not raw.get("enabled"):
        return False
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if (m.get("role") or "").strip().lower() != "user":
            continue
        if _user_has_image_parts(m):
            return True
    return False


async def apply_vision_precaption_if_needed(
    messages: list[dict[str, Any]],
    *,
    skip_precaption: bool = False,
) -> list[dict[str, Any]]:
    raw = config.get("agent.vision_precaption", {}) or {}
    if skip_precaption or not isinstance(raw, dict) or not raw.get("enabled"):
        return messages
    if not messages:
        return messages

    idx = -1
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if (m.get("role") or "").strip().lower() != "user":
            continue
        if _user_has_image_parts(m):
            idx = i
            break
    if idx < 0:
        return messages

    registry_name, fmt, model = _resolve_precaption_model()
    if not model:
        logger.warning(
            "[vision_precaption] enabled but no resolved model; set agent.vision_precaption.model_name "
            "or model / provider"
        )
        return messages
    if fmt not in _SUPPORTED_PROVIDERS:
        logger.warning(
            "[vision_precaption] format %s not supported (use openai or openai_compat registry model)",
            fmt,
        )
        return messages

    msg = messages[idx]
    content = msg.get("content")
    if not isinstance(content, list):
        return messages
    user_text, image_parts = _split_user_multimodal(content)
    if not image_parts:
        return messages

    instruction = str(raw.get("instruction") or "").strip() or (
        "请客观、详细地描述图片中的可见内容（物体、文字、场景、数量、颜色等），"
        "供后续文字对话模型使用。不要臆测画面无法确认的信息。"
    )
    prefix = str(raw.get("prefix") if raw.get("prefix") is not None else "【图像识别】\n")
    temperature = float(raw.get("temperature", 0.3))
    max_tokens = int(raw.get("max_tokens", 1024) or 1024)
    max_caption_chars = int(raw.get("max_caption_chars", 16000) or 16000)
    max_merged_chars = int(raw.get("max_merged_chars", 48000) or 48000)

    client_kw: dict[str, Any] = {"registry_name": registry_name, "model": model}
    to_raw = raw.get("timeout")
    if to_raw is not None:
        with contextlib.suppress(TypeError, ValueError):
            client_kw["timeout"] = int(to_raw)

    try:
        client = LLMFactory.get_client("vision_precaption", **client_kw)
        vision_messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": instruction}, *image_parts],
            }
        ]
        t0 = time.perf_counter()
        resp = await client.chat(
            messages=vision_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        caption_raw = _extract_assistant_text(resp)
        caption = _sanitize_merged_text(caption_raw, max_caption_chars)
        logger.info(
            "[vision_precaption] ok registry=%s model=%s elapsed_ms=%.0f caption_chars=%s",
            registry_name,
            model,
            elapsed_ms,
            len(caption),
        )
    except Exception as e:
        logger.warning(
            "[vision_precaption] call failed registry=%s model=%s timeout_cfg=%s images=%s: %s",
            registry_name,
            model,
            client_kw.get("timeout", "(default)"),
            len(image_parts),
            e,
            exc_info=True,
        )
        return _apply_precaption_failure(
            messages,
            idx,
            user_text,
            raw=raw,
            prefix=prefix,
            max_merged_chars=max_merged_chars,
            exc=e,
        )

    if not caption:
        logger.warning(
            "[vision_precaption] empty caption registry=%s model=%s; applying on_failure policy",
            registry_name,
            model,
        )
        return _apply_precaption_failure(
            messages,
            idx,
            user_text,
            raw=raw,
            prefix=prefix,
            max_merged_chars=max_merged_chars,
            exc=RuntimeError("empty_caption"),
        )

    merged = _sanitize_merged_text(
        "\n\n".join(x for x in (user_text, f"{prefix}{caption}") if x).strip(),
        max_merged_chars,
    )
    out = copy.deepcopy(messages)
    out[idx] = {**copy.deepcopy(msg), "content": merged}
    logger.debug("[vision_precaption] user message %s merged (%s chars)", idx, len(merged))
    return out
