from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.models.factory import LLMFactory

logger = get_logger(__name__)


class TaskKind(str, Enum):
    REASONING = "reasoning"
    CODE = "code"
    VISION = "vision"
    TOOLS = "tools"
    CHAT = "chat"
    GENERAL = "general"


@dataclass(frozen=True)
class ModelRoutingResult:
    provider: str
    model: str | None
    task_kind: TaskKind
    via: str


def _default_llm_pair() -> tuple[str, str | None]:
    prov = str(config.get("llm.default_provider", "openai") or "openai")
    block = config.get(f"{prov}_llm", {}) or {}
    m = block.get("model") if isinstance(block, dict) else None
    return prov, str(m) if m else None


def _route_entry(kind: TaskKind) -> dict[str, Any] | None:
    routes = config.get("agent.model_router.routes", {}) or {}
    if not isinstance(routes, dict):
        return None
    raw = routes.get(kind.value)
    return raw if isinstance(raw, dict) else None


def _materialize(kind: TaskKind) -> tuple[str, str | None]:
    """Resolve provider/model for a route row.

    If ``provider`` is empty, keep ``llm.default_provider`` but still honor a route-specific
    ``model`` (UI 「默认」厂商 + 自定义模型 ID). Previously an empty provider discarded the
    row's model and always used the global default pair.
    """
    entry = _route_entry(kind)
    if not entry:
        return _default_llm_pair()
    p_raw = entry.get("provider")
    m_raw = entry.get("model")
    prov = str(p_raw).strip().lower() if p_raw else ""
    mod_str = str(m_raw).strip() if m_raw else ""
    mod: str | None = mod_str if mod_str else None

    default_prov, default_mod = _default_llm_pair()

    if prov:
        return prov, mod

    if mod is not None:
        return default_prov, mod

    return default_prov, default_mod


def _extract_last_user_payload(messages: list[dict[str, Any]]) -> tuple[str, bool]:
    text_parts: list[str] = []
    has_image = False
    for m in reversed(messages):
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            text_parts.append(c)
            break
        if isinstance(c, list):
            for p in c:
                if not isinstance(p, dict):
                    continue
                t = str(p.get("type", "")).lower()
                if t in ("image", "image_url", "input_image"):
                    has_image = True
                if t == "text":
                    tx = p.get("text")
                    if isinstance(tx, str):
                        text_parts.append(tx)
            break
    return ("\n".join(text_parts).strip(), has_image)


_CODE_HINT = re.compile(
    r"(?m)(```|def\s+\w+\s*\(|class\s+\w+|import\s+\w+|printf?\(|console\.log)",
    re.IGNORECASE,
)
_REASONING_HINT = re.compile(r"(分析|证明|推导|为什么|深度|严谨|逻辑|证明题|复杂)", re.IGNORECASE)
_TOOLS_HINT = re.compile(
    r"(搜索|查一下|查询|打开网页|浏览器|实时|天气|新闻|http://|https://)", re.IGNORECASE
)
_CHAT_GREETING = re.compile(
    r"^(你好|您好|hi\b|hello\b|嗨|在吗|早上好|晚上好)[\s!！。.?？]*$", re.IGNORECASE
)


def heuristic_task_kind(messages: list[dict[str, Any]]) -> TaskKind:
    text, has_image = _extract_last_user_payload(messages)
    if has_image:
        return TaskKind.VISION
    if not text:
        return TaskKind.GENERAL
    s = text.strip()
    if len(s) < 18 and _CHAT_GREETING.match(s):
        return TaskKind.CHAT
    if _CODE_HINT.search(text):
        return TaskKind.CODE
    if _TOOLS_HINT.search(text):
        return TaskKind.TOOLS
    if _REASONING_HINT.search(text) or len(text) > 800:
        return TaskKind.REASONING
    return TaskKind.GENERAL


def _parse_task_label(raw: str) -> TaskKind | None:
    t = raw.strip().lower()
    for k in TaskKind:
        if k.value == t:
            return k
    return None


def _provider_block_default_model(provider_key: str) -> str:
    block = config.get(f"{provider_key.strip().lower()}_llm", {}) or {}
    if not isinstance(block, dict):
        return ""
    return str(block.get("model") or "").strip()


async def _llm_classify_task_kind(messages: list[dict[str, Any]]) -> TaskKind:
    cls_cfg = config.get("agent.model_router.classifier", {}) or {}
    if not isinstance(cls_cfg, dict):
        cls_cfg = {}
    prov = (
        str(cls_cfg.get("provider") or config.get("llm.default_provider") or "openai")
        .strip()
        .lower()
    )
    cls_raw = cls_cfg.get("model")
    cls_model = str(cls_raw).strip() if cls_raw is not None else ""
    fallback_model = _provider_block_default_model(prov)
    effective_model = cls_model or fallback_model
    temperature = float(cls_cfg.get("temperature", 0.1))
    max_tokens = int(cls_cfg.get("max_tokens", 256) or 256)

    text, has_image = _extract_last_user_payload(messages)
    if has_image:
        return TaskKind.VISION

    snippet = text[:4000] if text else ""
    prompt = (
        "You route user requests to a task label. Reply JSON only, no markdown.\n"
        'Schema: {"task":"reasoning|code|vision|tools|chat|general"}\n'
        "Labels: reasoning=deep analysis; code=programming; vision=images present "
        "(already handled—use general if unsure); tools=needs web search/tools; "
        "chat=small talk; general=default.\n"
        f"User message:\n{snippet}"
    )

    logger.info(
        "[model_router] classifier request provider=%s effective_model=%s "
        "(intent_field=%r fallback_%s_llm=%r)",
        prov,
        effective_model or "(none)",
        cls_model,
        prov,
        fallback_model,
    )

    client = LLMFactory.get_client(
        "model_router_classifier",
        provider=prov,
        **({"model": effective_model} if effective_model else {}),
    )
    resp = await client.chat(
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False,
    )
    content = ""
    if isinstance(resp, dict):
        choices = resp.get("choices", [])
        if choices:
            content = str(choices[0].get("message", {}).get("content", "") or "")
    else:
        content = str(resp)

    m = re.search(r"\{[^{}]*\"task\"\s*:\s*\"([^\"]+)\"[^{}]*\}", content)
    if m:
        parsed = _parse_task_label(m.group(1))
        if parsed:
            return parsed

    try:
        obj = json.loads(content)
        if isinstance(obj, dict):
            parsed = _parse_task_label(str(obj.get("task", "")))
            if parsed:
                return parsed
    except json.JSONDecodeError:
        pass

    return TaskKind.GENERAL


async def resolve_task_kind(
    messages: list[dict[str, Any]],
    *,
    router_hint: str | None,
    mode: str,
) -> tuple[TaskKind, str]:
    if router_hint:
        hk = _parse_task_label(router_hint)
        if hk:
            return hk, "hint"

    text, has_image = _extract_last_user_payload(messages)
    if has_image:
        return TaskKind.VISION, "vision_guard"

    if mode == "heuristic":
        return heuristic_task_kind(messages), "heuristic"

    if mode == "llm":
        kind = await _llm_classify_task_kind(messages)
        return kind, "llm"

    h = heuristic_task_kind(messages)
    if h != TaskKind.GENERAL:
        return h, "heuristic"

    kind = await _llm_classify_task_kind(messages)
    return kind, "llm"


async def resolve_model_routing(
    messages: list[dict[str, Any]],
    *,
    request_provider: str | None = None,
    request_model: str | None = None,
    router_hint: str | None = None,
    enabled_override: bool | None = None,
) -> ModelRoutingResult:
    mr_cfg = config.get("agent.model_router", {}) or {}
    if not isinstance(mr_cfg, dict):
        mr_cfg = {}
    enabled = mr_cfg.get("enabled", False)
    if enabled_override is not None:
        enabled = bool(enabled_override)

    rp = (request_provider or "").strip()
    rm = (request_model or "").strip()

    if not enabled:
        dp, dm = _default_llm_pair()
        return ModelRoutingResult(
            provider=rp or dp,
            model=rm or dm,
            task_kind=TaskKind.GENERAL,
            via="disabled",
        )

    if rp or rm:
        dp, dm = _default_llm_pair()
        return ModelRoutingResult(
            provider=rp or dp,
            model=rm or dm,
            task_kind=TaskKind.GENERAL,
            via="manual",
        )

    mode = str(mr_cfg.get("mode", "hybrid") or "hybrid").strip().lower()
    if mode not in ("heuristic", "llm", "hybrid"):
        mode = "hybrid"

    kind, via_inner = await resolve_task_kind(messages, router_hint=router_hint, mode=mode)
    p, m = _materialize(kind)
    logger.debug(
        "[model_router] task_kind=%s provider=%s model=%s via=%s",
        kind.value,
        p,
        m,
        via_inner,
    )
    return ModelRoutingResult(provider=p, model=m, task_kind=kind, via=via_inner)
