"""Compat and native ReAct streaming loops."""

from __future__ import annotations

import asyncio
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
from ly_next.agent.prompt_templates import (
    get_native_system_prefix,
)
from ly_next.agent.react.helpers import (
    aborted,
    assistant_turn_from_response,
    compact_tools,
    extract_text,
    inject_tool_manifest,
    length_continuation_user_text,
    merge_system_instruction,
    parse_openai_completion,
    preview_json,
    run_tool_with_obs,
    sanitize_dialog_messages,
    validate_decision,
)
from ly_next.agent.react.tool_exec import execute_native_tool_call
from ly_next.agent.tool_filter import get_filtered_tools_for_deps, get_openai_tools_for_deps, list_tools_payload
from ly_next.core.context_budget import (
    cumulative_budget_limit,
    effective_context_window_tokens,
    estimate_dialog_tokens,
    length_continuation_max,
    parse_completion_meta,
    prune_old_tool_message_contents,
)
from ly_next.core.logger import get_logger
from ly_next.core.run_telemetry import record_tool_timing

logger = get_logger(__name__)


async def _stream_messages_answer(
    deps: AgentDeps,
    messages: list[dict[str, Any]],
    *,
    status_detail: str,
) -> AsyncIterator[dict[str, Any]]:
    yield {"type": "status", "phase": "answer", "detail": status_detail}
    parts: list[str] = []
    async for piece in deps.iter_messages_stream(messages):
        parts.append(piece)
        yield {"type": "chunk", "content": piece}
    text = "".join(parts).strip() or "No response."
    yield {"type": "final", "content": text, "chunked": bool(parts)}


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
        async for ev in _stream_messages_answer(
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
    if not deps.tool_registry:
        raise RuntimeError("no tool registry")

    openai_tools, allowed_names, _objs = get_openai_tools_for_deps(deps)
    allowed_set = set(allowed_names)

    dialog = merge_system_instruction(sanitize_dialog_messages(list(messages)))
    logger.debug(
        "[agent.native] registry_tools=%s visible_tools=%s",
        len(deps.tool_registry.list_tools()) if deps.tool_registry else 0,
        len(allowed_names),
    )
    if openai_tools:
        inject_tool_manifest(dialog, allowed_names)
        logger.info(
            "[agent.native] Registered tools exposed to model (%s): %s",
            len(allowed_names),
            ", ".join(allowed_names),
        )

    if not openai_tools:
        yield {
            "type": "status",
            "phase": "direct",
            "detail": "当前过滤条件下无可用工具，改为直接对话",
        }
        q = last_user_query(messages)
        if not q:
            q = "\n".join(
                f"{(m.get('role') or 'user')}: {m.get('content', '')}" for m in (messages or [])
            ).strip()
        prompt = (
            f"{get_native_system_prefix()}\n\nUser request:\n{q}\n\nAnswer without tools."
        )
        async for ev in _stream_messages_answer(
            deps, [{"role": "user", "content": prompt}], status_detail="直接回答"
        ):
            yield ev
        return

    last_sig = ""
    same_sig_count = 0
    fail_streak = 0
    run_tag = secrets.token_hex(6)
    budget_used = 0
    cap_ceiling = cumulative_budget_limit()
    ctx_window = effective_context_window_tokens(deps.model)

    for iteration in range(deps.max_steps):
        if aborted(deps):
            yield {"type": "final", "content": "（对话已由用户中断）"}
            return
        if cap_ceiling > 0 and budget_used >= cap_ceiling:
            yield {
                "type": "final",
                "content": "Stopped: cumulative completion-token budget exhausted.",
            }
            return

        yield {
            "type": "status",
            "phase": "llm",
            "iteration": iteration,
            "detail": "请求模型（function calling / tool_calls）",
        }
        dialog = prune_old_tool_message_contents(
            dialog, model=deps.model, max_output_tokens=deps.max_tokens
        )
        approx_in = estimate_dialog_tokens(dialog)
        if approx_in > ctx_window * 0.92:
            logger.warning(
                "[agent.native] dialog ~%s est. tokens vs window %s (tool bodies may be pruned)",
                approx_in,
                ctx_window,
            )

        try:
            cont_i = 0
            max_len_cont = length_continuation_max()
            resp: dict[str, Any]
            raw_msg: dict[str, Any] | None = None
            tool_calls: list[dict[str, Any]] = []

            while True:
                if aborted(deps):
                    yield {"type": "final", "content": "（对话已由用户中断）"}
                    return

                streamed_parts: list[str] = []
                resp: dict[str, Any] = {}
                raw_msg: dict[str, Any] | None = None
                tool_calls: list[dict[str, Any]] = []

                async for stream_ev in deps.iter_chat_with_tools(dialog, openai_tools):
                    if stream_ev.get("type") == "chunk":
                        piece = str(stream_ev.get("content") or "")
                        if piece:
                            streamed_parts.append(piece)
                            yield {"type": "chunk", "content": piece}
                    elif stream_ev.get("type") == "completion":
                        resp = stream_ev.get("response") or {}
                        raw_msg, tool_calls = parse_openai_completion(resp)

                if raw_msg is None:
                    keys = list(resp.keys()) if isinstance(resp, dict) else []
                    logger.warning(
                        "[agent.native] Unrecognized chat completion shape (top-level keys=%s); "
                        "check gateway compatibility with OpenAI Chat Completions.",
                        keys[:20],
                    )
                    raise RuntimeError("unexpected completion payload")

                ct, _tt, fr = parse_completion_meta(resp)
                if ct is not None:
                    budget_used += ct
                else:
                    c0 = raw_msg.get("content")
                    s = c0 if isinstance(c0, str) else str(c0 or "")
                    budget_used += max(0, len(s) // 4)

                if cap_ceiling > 0 and budget_used >= cap_ceiling and not tool_calls:
                    content = raw_msg.get("content")
                    out = (
                        (content or "").strip()
                        if isinstance(content, str)
                        else str(content or "").strip()
                    )
                    if not out and streamed_parts:
                        out = "".join(streamed_parts).strip()
                    yield {"type": "status", "phase": "answer", "detail": "输出预算已达上限"}
                    yield {
                        "type": "final",
                        "content": out or "Stopped: cumulative completion-token budget exhausted.",
                        "chunked": bool(streamed_parts),
                    }
                    return

                if tool_calls:
                    break

                content = raw_msg.get("content")
                out = (
                    (content or "").strip()
                    if isinstance(content, str)
                    else str(content or "").strip()
                )
                if not out and streamed_parts:
                    out = "".join(streamed_parts).strip()
                if fr in ("length", "max_tokens") and cont_i < max_len_cont:
                    yield {
                        "type": "status",
                        "phase": "llm",
                        "iteration": iteration,
                        "detail": f"输出因长度截断，续写 ({cont_i + 1}/{max_len_cont})",
                    }
                    dialog.append(assistant_turn_from_response(raw_msg))
                    dialog.append({"role": "user", "content": length_continuation_user_text()})
                    cont_i += 1
                    continue

                yield {"type": "status", "phase": "answer", "detail": "模型返回最终回答"}
                yield {
                    "type": "final",
                    "content": out or "No response.",
                    "chunked": bool(streamed_parts),
                }
                return

            dialog.append(assistant_turn_from_response(raw_msg))

        except Exception as e:
            logger.warning("[agent.native] chat_with_tools failed: %s", e)
            raise

        names = [tc["name"] for tc in tool_calls]
        yield {
            "type": "status",
            "phase": "tools",
            "iteration": iteration,
            "detail": f"模型发起 {len(tool_calls)} 次函数调用: {', '.join(names)}",
            "tool_names": names,
        }

        planned: list[dict[str, Any]] = []
        for idx, tc in enumerate(tool_calls):
            name = tc["name"]
            raw_args = tc.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                if not isinstance(args, dict):
                    args = {}
            except json.JSONDecodeError:
                args = {}

            if aborted(deps):
                yield {"type": "final", "content": "（对话已由用户中断）"}
                return

            tcid = tc.get("id") or f"call_{iteration}_{idx}_{name}"
            yield {
                "type": "tool_start",
                "tool": name,
                "call_id": str(tcid),
                "iteration": iteration,
                "args_preview": preview_json(args, limit=1200),
            }
            planned.append(
                {
                    "name": name,
                    "args": args,
                    "call_id": str(tcid),
                }
            )

        if len(planned) == 1:
            item = planned[0]
            outcomes = [
                await execute_native_tool_call(
                    deps,
                    name=item["name"],
                    args=item["args"],
                    call_id=item["call_id"],
                    run_tag=run_tag,
                    allowed_set=allowed_set,
                )
            ]
        else:
            outcomes = await asyncio.gather(
                *[
                    execute_native_tool_call(
                        deps,
                        name=item["name"],
                        args=item["args"],
                        call_id=item["call_id"],
                        run_tag=run_tag,
                        allowed_set=allowed_set,
                    )
                    for item in planned
                ]
            )

        for _item, outcome in zip(planned, outcomes, strict=True):
            name = outcome["name"]
            args = outcome["args"]
            yield {
                "type": "tool_done",
                "tool": name,
                "call_id": outcome["call_id"],
                "iteration": iteration,
                "success": outcome["ok"],
                "result_preview": outcome["preview"],
            }

            sig = outcome["sig"]
            same_sig_count = same_sig_count + 1 if sig == last_sig else 1
            last_sig = sig

            if not outcome["ok"]:
                fail_streak += 1
            else:
                fail_streak = 0

            if same_sig_count >= deps.loop_max_repeat_same_tool:
                yield {"type": "final", "content": "Stopped: repeated identical tool calls."}
                return
            if fail_streak >= deps.loop_max_consecutive_tool_failures:
                yield {"type": "final", "content": "Stopped: too many consecutive tool failures."}
                return

            dialog.append(
                {
                    "role": "tool",
                    "tool_call_id": outcome["call_id"],
                    "content": outcome["tool_body"],
                }
            )

    yield {"type": "final", "content": "Maximum steps reached."}
