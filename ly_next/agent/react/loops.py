"""Compat and native ReAct streaming loops."""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import AsyncIterator
from typing import Any

from ly_next.agent.deps import AgentDeps
from ly_next.agent.json_extract import parse_json_object
from ly_next.agent.prompt_augment import last_user_query
from ly_next.agent.prompt_templates import (
    build_compat_decision_prompt as _build_compat_decision_prompt,
)
from ly_next.agent.react.helpers import (
    aborted,
    compact_tools,
    extract_text,
    preview_json,
    run_tool_with_obs,
    validate_decision,
)
from ly_next.agent.tool_filter import get_filtered_tools_for_deps, list_tools_payload
from ly_next.agent.turn_engine import iter_direct_answer
from ly_next.core.logger import get_logger
from ly_next.core.run_telemetry import record_tool_timing

logger = get_logger(__name__)


def build_compat_decision_prompt(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    scratchpad: str,
) -> str:
    return _build_compat_decision_prompt(
        dialog=extract_text(messages),
        tools=tools,
        scratchpad=scratchpad,
    )


async def iter_compat_react(
    messages: list[dict[str, Any]],
    deps: AgentDeps,
) -> AsyncIterator[dict[str, Any]]:
    if not deps.tool_registry:
        raise RuntimeError("no tool registry")

    objs, _names = get_filtered_tools_for_deps(deps)
    raw_tools = list_tools_payload(objs)
    tools = compact_tools(raw_tools)
    tool_names = [t["name"] for t in tools]

    if not tools:
        yield {"type": "status", "phase": "direct", "detail": "当前过滤条件下无可用工具，直接回答"}
        q = last_user_query(messages) or extract_text(messages)
        async for ev in iter_direct_answer(
            deps, [{"role": "user", "content": q}], status_detail="直接回答"
        ):
            yield ev
        return

    scratchpad = ""
    run_tag_c = secrets.token_hex(6)
    last_sig = ""
    same_sig_count = 0
    fail_streak = 0

    for iteration in range(deps.max_steps):
        if aborted(deps):
            yield {"type": "final", "content": "（对话已由用户中断）"}
            return
        yield {
            "type": "status",
            "phase": "llm",
            "iteration": iteration,
            "detail": "兼容模式：请求模型输出 JSON 决策",
        }
        prompt = build_compat_decision_prompt(messages=messages, tools=tools, scratchpad=scratchpad)
        if aborted(deps):
            yield {"type": "final", "content": "（对话已由用户中断）"}
            return
        text = (await deps.call_llm(prompt)).strip()

        try:
            obj = parse_json_object(text)
            kind, payload = validate_decision(obj, tool_names)
        except Exception as e:
            msg = str(e).strip() or repr(e)
            yield {
                "type": "status",
                "phase": "repair",
                "iteration": iteration,
                "detail": f"模型输出非 JSON/不合法，尝试修复：{msg}",
            }
            repair = (
                "Fix the following into a valid JSON decision that follows the schema exactly. "
                "Output JSON only. Escape newlines inside strings as \\n.\n\n"
                f"Allowed tools: {', '.join(tool_names)}\n\n"
                f"Bad output:\n{text[:6000]}"
            )
            fixed = ""
            try:
                fixed = (
                    await deps.call_llm_limited(repair, max_tokens=deps.max_tokens, temperature=0.1)
                ).strip()
                obj = parse_json_object(fixed)
                kind, payload = validate_decision(obj, tool_names)
            except Exception as e2:
                err2 = str(e2).strip() or repr(e2)
                logger.warning(
                    "[agent.compat] JSON repair failed iteration=%s: %s; raw_len=%s fixed_len=%s",
                    iteration,
                    err2,
                    len(text),
                    len(fixed),
                )
                yield {
                    "type": "final",
                    "content": (
                        f"模型决策 JSON 无法解析，对话已停止。\n首次错误：{msg}\n修复错误：{err2}"
                    ),
                }
                return

        if kind == "final":
            yield {"type": "final", "content": str(payload.get("final") or "")}
            return

        name = str(payload.get("name") or "").strip()
        args = payload.get("args") or {}
        if not isinstance(args, dict):
            args = {}

        if aborted(deps):
            yield {"type": "final", "content": "（对话已由用户中断）"}
            return

        yield {
            "type": "tool_start",
            "tool": name,
            "call_id": f"compat_{iteration}_{name}",
            "iteration": iteration,
            "args_preview": preview_json(args, limit=1200),
        }

        t_tool = time.perf_counter()
        result, obs = await run_tool_with_obs(
            deps,
            name,
            args,
            call_id=f"compat_{iteration}_{name}",
            run_tag=run_tag_c,
        )
        ok = not (isinstance(result, dict) and result.get("success") is False)
        record_tool_timing(name, (time.perf_counter() - t_tool) * 1000.0, ok)
        preview = obs if len(obs) <= 2000 else obs[:1999] + "…"
        yield {
            "type": "tool_done",
            "tool": name,
            "call_id": f"compat_{iteration}_{name}",
            "iteration": iteration,
            "success": ok,
            "result_preview": preview,
        }

        sig = json.dumps({"name": name, "args": args}, sort_keys=True, ensure_ascii=False)
        same_sig_count = same_sig_count + 1 if sig == last_sig else 1
        last_sig = sig

        if isinstance(result, dict) and result.get("success") is False:
            fail_streak += 1
        else:
            fail_streak = 0

        scratchpad += f"\nCALL {name} args={json.dumps(args, ensure_ascii=False)}\nOBS {obs}\n"

        if same_sig_count >= deps.loop_max_repeat_same_tool:
            yield {"type": "final", "content": "Stopped: repeated identical tool calls."}
            return
        if fail_streak >= deps.loop_max_consecutive_tool_failures:
            yield {"type": "final", "content": "Stopped: too many consecutive tool failures."}
            return

    yield {"type": "final", "content": "Maximum steps reached."}


async def iter_native_react(
    messages: list[dict[str, Any]],
    deps: AgentDeps,
) -> AsyncIterator[dict[str, Any]]:
    from ly_next.agent.react.native_steps import iter_native_react_via_session

    async for ev in iter_native_react_via_session(messages, deps):
        yield ev
