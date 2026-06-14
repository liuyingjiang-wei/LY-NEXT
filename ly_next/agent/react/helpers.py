"""Shared helpers for ReAct agent loops and graph nodes."""

from __future__ import annotations

import asyncio
import json
from functools import partial
from typing import Any

import httpx

from ly_next.agent.deps import AgentDeps
from ly_next.agent.image_reply import format_image_tool_observation, record_tool_result
from ly_next.agent.prompt_templates import format_tool_manifest_block
from ly_next.agent.tool_filter import get_filtered_tools_for_deps
from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.core.tool_result_spill import format_tool_result_for_llm

logger = get_logger(__name__)


def aborted(deps: AgentDeps) -> bool:
    return deps.stop_event is not None and deps.stop_event.is_set()


def length_continuation_user_text() -> str:
    raw = config.get("agent.output_token_budget", {}) or {}
    if isinstance(raw, dict):
        p = raw.get("continuation_prompt")
        if isinstance(p, str) and p.strip():
            return p.strip()
    return (
        "Your previous reply was truncated by the model output limit. "
        "Continue from where you stopped; produce only the remaining user-visible text."
    )


def visible_tools_include_mcp(deps: AgentDeps) -> bool:
    if not deps.tool_registry or not deps.use_tools:
        return False
    try:
        objs, _ = get_filtered_tools_for_deps(deps)
    except Exception as e:
        logger.debug("tool filter for MCP visibility failed: %s", e)
        return False
    return any((t.definition.category or "").strip().lower() == "mcp" for t in objs)


def auto_use_compat_first_for_mcp(deps: AgentDeps) -> bool:
    if (deps.tool_call_mode or "auto").strip().lower() != "auto":
        return False
    if not config.get("agent.prefer_compat_when_mcp_tools", True):
        return False
    return visible_tools_include_mcp(deps)


async def run_tool_with_obs(
    deps: AgentDeps,
    name: str,
    args: dict[str, Any],
    *,
    call_id: str,
    run_tag: str,
) -> tuple[Any, str]:
    if deps.tool_registry is None:
        raise RuntimeError("tool_registry is not configured")
    result = await deps.tool_registry.call_tool(name, args)
    record_tool_result(deps, name, result)
    obs = await asyncio.to_thread(
        partial(format_tool_result_for_llm, name, call_id, result, run_tag=run_tag)
    )
    return result, format_image_tool_observation(name, obs)


def tool_result_as_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False)
    except TypeError:
        return str(result)


def sanitize_dialog_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages or []:
        role = (m.get("role") or "user").strip().lower()
        if role not in ("system", "user", "assistant", "tool"):
            continue
        if role == "tool":
            tcid = m.get("tool_call_id")
            if not tcid:
                continue
            ttxt = tool_result_as_text(m.get("content"))
            st = str(ttxt).strip()
            if not st or st in ("{}", "[]", "null", '""'):
                ttxt = "(tool completed with no output)"
            item: dict[str, Any] = {
                "role": "tool",
                "tool_call_id": str(tcid),
                "content": ttxt,
            }
            out.append(item)
            continue
        content = m.get("content")
        if isinstance(content, dict):
            content = json.dumps(content, ensure_ascii=False)
        elif content is None:
            content = ""
        else:
            content = str(content)
        item = {"role": role, "content": content}
        if role == "assistant" and m.get("tool_calls"):
            item["tool_calls"] = m["tool_calls"]
        out.append(item)
    return out


def merge_system_instruction(
    messages: list[dict[str, Any]],
    *,
    persona_block: str = "",
) -> list[dict[str, Any]]:
    from ly_next.agent.persona import combine_native_system_prefix

    prefix = combine_native_system_prefix(persona_block) + "\n\n"
    out: list[dict[str, Any]] = []
    merged = False
    for m in messages:
        if (m.get("role") or "").strip().lower() == "system" and not merged:
            merged = True
            prev = m.get("content") or ""
            prev = json.dumps(prev, ensure_ascii=False) if isinstance(prev, dict) else str(prev)
            out.append({"role": "system", "content": prefix + prev})
        else:
            out.append(dict(m))
    if not merged:
        out.insert(0, {"role": "system", "content": prefix.strip()})
    return out


def assistant_turn_from_response(message: dict[str, Any]) -> dict[str, Any]:
    turn: dict[str, Any] = {"role": "assistant", "content": message.get("content")}
    if message.get("tool_calls"):
        turn["tool_calls"] = message["tool_calls"]
    return turn


def assistant_message_from_choice(resp: dict[str, Any]) -> dict[str, Any] | None:
    choices = resp.get("choices") if isinstance(resp, dict) else None
    if not isinstance(choices, list) or not choices:
        return None
    ch0 = choices[0]
    if not isinstance(ch0, dict):
        return None
    msg = ch0.get("message")
    if isinstance(msg, dict):
        return msg
    if ch0.get("role") or ch0.get("content") is not None or ch0.get("tool_calls"):
        return ch0
    return None


def parse_openai_completion(
    resp: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    raw_msg = assistant_message_from_choice(resp)
    if raw_msg is None:
        top = resp.get("message") if isinstance(resp, dict) else None
        raw_msg = top if isinstance(top, dict) else None
    if raw_msg is None:
        return None, []
    parsed_calls: list[dict[str, Any]] = []
    for tc in raw_msg.get("tool_calls") or []:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
        name = (fn.get("name") or "").strip()
        if not name:
            continue
        parsed_calls.append(
            {
                "id": str(tc.get("id") or ""),
                "name": name,
                "arguments": fn.get("arguments") if isinstance(fn.get("arguments"), str) else "{}",
            }
        )
    return raw_msg, parsed_calls


def inject_tool_manifest(dialog: list[dict[str, Any]], tool_names: list[str]) -> None:
    if not tool_names:
        return
    block = format_tool_manifest_block(list(tool_names))
    for i, m in enumerate(dialog):
        if (m.get("role") or "").strip().lower() != "system":
            continue
        c = m.get("content")
        if isinstance(c, dict):
            c = json.dumps(c, ensure_ascii=False)
        elif c is None:
            c = ""
        else:
            c = str(c)
        dialog[i] = {**m, "content": c + block}
        return
    dialog.insert(0, {"role": "system", "content": block.strip()})


def preview_json(value: Any, limit: int = 900) -> str:
    try:
        s = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    except TypeError:
        s = str(value)
    if len(s) > limit:
        return s[: limit - 1] + "…"
    return s


def looks_tool_blind_response(text: str) -> bool:
    s = (text or "").strip().lower()
    if not s:
        return False
    needles = [
        "目前没有可用的工具",
        "cannot access external webpages directly",
        "tool limitations",
        "没有可用的工具",
        "不能访问外部网页",
        "无法访问外部网页",
    ]
    return any(n in s for n in needles)


def extract_text(messages: list[dict[str, Any]]) -> str:
    parts = []
    for m in messages or []:
        role = (m.get("role") or "user").strip()
        content = m.get("content", "")
        if isinstance(content, dict):
            content = (
                content.get("text")
                or content.get("content")
                or json.dumps(content, ensure_ascii=False)
            )
        if content is None:
            content = ""
        parts.append(f"{role}: {content}")
    return "\n".join(parts).strip()


def compact_tools(raw_tools: list[dict]) -> list[dict]:
    cleaned = []
    for t in raw_tools or []:
        name = t.get("name") or ""
        if not name:
            continue
        desc = t.get("description") or ""
        schema = t.get("inputSchema") or t.get("parameters", {})
        props = schema.get("properties") if isinstance(schema, dict) else None
        if isinstance(props, dict) and props:
            keys = ", ".join(list(props.keys())[:30])
            desc = f"{desc} (args: {keys})"
        cleaned.append({"name": name, "description": desc})
    return cleaned


def validate_decision(obj: dict[str, Any], tool_names: list[str]) -> tuple[str, dict[str, Any]]:
    t = (obj.get("type") or "").strip().lower()

    if t == "final":
        return "final", {"final": str(obj.get("final") or "")}

    if t == "tool":
        name = str(obj.get("name") or "").strip()
        if tool_names and name not in tool_names:
            raise ValueError(f"tool not allowed: {name}")
        args = obj.get("args") or {}
        if not isinstance(args, dict):
            raise ValueError("args must be an object")
        return "tool", {"name": name, "args": args}

    raise ValueError("type must be 'tool' or 'final'")


def format_agent_error(exc: BaseException) -> str:
    text = str(exc).strip()
    name = type(exc).__name__
    if text:
        return f"{name}: {text}"
    return name


def is_llm_timeout_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TimeoutException):
        return True
    msg = str(exc).lower()
    return "timeout" in msg or "timed out" in msg


def should_skip_native_legacy_fallback(exc: BaseException) -> bool:
    if is_llm_timeout_error(exc):
        return True
    if isinstance(exc, httpx.RequestError):
        return True
    if isinstance(exc, RuntimeError):
        msg = str(exc).lower()
        if "timeout" in msg or "openai_compat" in msg:
            return True
    return False


def native_react_failure_message(exc: BaseException) -> str:
    summary = format_agent_error(exc)
    if is_llm_timeout_error(exc):
        return (
            f"模型请求超时（{summary}）。"
            "请增大 llm.agent_request_timeout（Agent 专用）或 llm.request_timeout。"
        )
    return f"Agent 调用失败：{summary}"


def react_engine() -> str:
    return str(config.get("agent.react_engine", "native")).strip().lower()


def react_loop_kind(deps: AgentDeps) -> str:
    if deps._custom_llm_call or not deps.use_tools:
        return "legacy"
    engine = react_engine()
    mode = (deps.tool_call_mode or "auto").strip().lower()
    if mode == "compat" or auto_use_compat_first_for_mcp(deps):
        return "compat"
    if engine == "langgraph_native" and mode in ("auto", "native") and deps.native_tool_calls:
        return "langgraph_native"
    if mode in ("auto", "native") and deps.native_tool_calls:
        return "native"
    return "legacy"


def tool_blind_fallback(deps: AgentDeps) -> str:
    mode = (deps.tool_call_mode or "auto").strip().lower()
    return "compat" if mode == "auto" else "legacy"
