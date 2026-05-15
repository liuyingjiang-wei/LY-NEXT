"""ReAct loops (compat JSON / native tool_calls / LangGraph legacy)."""

import asyncio
import json
import re
import secrets
import time
from collections.abc import AsyncIterator
from functools import partial
from typing import Any

from langgraph.graph import END, StateGraph

from ly_next.agent.deps import AgentDeps, create_agent_deps
from ly_next.agent.prompt_augment import last_user_query
from ly_next.agent.prompt_templates import (
    build_compat_decision_prompt,
    build_plan_decision_prompt,
    format_tool_manifest_block,
    get_native_system_prefix,
)
from ly_next.agent.scratchpad_compress import compress_scratchpad
from ly_next.agent.state import AgentState, create_initial_state
from ly_next.agent.tool_filter import filter_tools_for_agent, list_tools_payload
from ly_next.core.config import config
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
from ly_next.core.tool_result_spill import format_tool_result_for_llm

logger = get_logger(__name__)


def _aborted(deps: AgentDeps) -> bool:
    return deps.stop_event is not None and deps.stop_event.is_set()


def _length_continuation_user_text() -> str:
    raw = config.get("agent.output_token_budget", {}) or {}
    if isinstance(raw, dict):
        p = raw.get("continuation_prompt")
        if isinstance(p, str) and p.strip():
            return p.strip()
    return (
        "Your previous reply was truncated by the model output limit. "
        "Continue from where you stopped; produce only the remaining user-visible text."
    )


def _visible_tools_include_mcp(deps: AgentDeps) -> bool:
    if not deps.tool_registry or not deps.use_tools:
        return False
    try:
        objs, _ = filter_tools_for_agent(
            deps.tool_registry,
            allow_tools=deps.tool_allow_tools,
            deny_tools=deps.tool_deny_tools,
            allow_categories=deps.tool_allow_categories,
            max_tier=deps.tool_max_tier,
            max_tools=deps.max_tools,
        )
    except Exception:
        return False
    return any((t.definition.category or "").strip().lower() == "mcp" for t in objs)


def _auto_use_compat_first_for_mcp(deps: AgentDeps) -> bool:
    if (deps.tool_call_mode or "auto").strip().lower() != "auto":
        return False
    if not config.get("agent.prefer_compat_when_mcp_tools", True):
        return False
    return _visible_tools_include_mcp(deps)


def _tool_result_as_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False)
    except TypeError:
        return str(result)


def _sanitize_dialog_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages or []:
        role = (m.get("role") or "user").strip().lower()
        if role not in ("system", "user", "assistant", "tool"):
            continue
        if role == "tool":
            tcid = m.get("tool_call_id")
            if not tcid:
                continue
            ttxt = _tool_result_as_text(m.get("content"))
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


def _merge_system_instruction(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prefix = get_native_system_prefix() + "\n\n"
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


def _assistant_turn_from_response(message: dict[str, Any]) -> dict[str, Any]:
    turn: dict[str, Any] = {"role": "assistant", "content": message.get("content")}
    if message.get("tool_calls"):
        turn["tool_calls"] = message["tool_calls"]
    return turn


def _assistant_message_from_choice(resp: dict[str, Any]) -> dict[str, Any] | None:
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


def _parse_openai_completion(
    resp: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    raw_msg = _assistant_message_from_choice(resp)
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


def _inject_tool_manifest(dialog: list[dict[str, Any]], tool_names: list[str]) -> None:
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


def _preview_json(value: Any, limit: int = 900) -> str:
    try:
        s = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    except TypeError:
        s = str(value)
    if len(s) > limit:
        return s[: limit - 1] + "…"
    return s


def _looks_tool_blind_response(text: str) -> bool:
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


def _build_compat_decision_prompt(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    scratchpad: str,
) -> str:
    return build_compat_decision_prompt(
        dialog=_extract_text(messages),
        tools=tools,
        scratchpad=scratchpad,
    )


async def _iter_compat_react(
    messages: list[dict[str, Any]],
    deps: AgentDeps,
) -> AsyncIterator[dict[str, Any]]:
    if not deps.tool_registry:
        raise RuntimeError("no tool registry")

    objs, _names = filter_tools_for_agent(
        deps.tool_registry,
        allow_tools=deps.tool_allow_tools,
        deny_tools=deps.tool_deny_tools,
        allow_categories=deps.tool_allow_categories,
        max_tier=deps.tool_max_tier,
        max_tools=deps.max_tools,
    )
    raw_tools = list_tools_payload(objs)
    tools = _compact_tools(raw_tools)
    tool_names = [t["name"] for t in tools]

    if not tools:
        yield {"type": "status", "phase": "direct", "detail": "当前过滤条件下无可用工具，直接回答"}
        q = last_user_query(messages) or _extract_text(messages)
        text = await deps.call_llm(q)
        yield {"type": "final", "content": text.strip()}
        return

    scratchpad = ""
    run_tag_c = secrets.token_hex(6)
    last_sig = ""
    same_sig_count = 0
    fail_streak = 0

    for iteration in range(deps.max_steps):
        if _aborted(deps):
            yield {"type": "final", "content": "（对话已由用户中断）"}
            return
        yield {
            "type": "status",
            "phase": "llm",
            "iteration": iteration,
            "detail": "兼容模式：请求模型输出 JSON 决策",
        }
        prompt = _build_compat_decision_prompt(
            messages=messages, tools=tools, scratchpad=scratchpad
        )
        if _aborted(deps):
            yield {"type": "final", "content": "（对话已由用户中断）"}
            return
        text = (await deps.call_llm(prompt)).strip()

        try:
            obj = _extract_json_obj(text)
            kind, payload = _validate_decision(obj, tool_names)
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
                "Output JSON only.\n\n"
                f"Allowed tools: {', '.join(tool_names)}\n\n"
                f"Bad output:\n{text}"
            )
            fixed = (await deps.call_llm(repair)).strip()
            obj = _extract_json_obj(fixed)
            kind, payload = _validate_decision(obj, tool_names)

        if kind == "final":
            yield {"type": "final", "content": str(payload.get("final") or "")}
            return

        name = str(payload.get("name") or "").strip()
        args = payload.get("args") or {}
        if not isinstance(args, dict):
            args = {}

        yield {
            "type": "tool_start",
            "tool": name,
            "call_id": f"compat_{iteration}_{name}",
            "iteration": iteration,
            "args_preview": _preview_json(args, limit=1200),
        }

        t_tool = time.perf_counter()
        result = await deps.tool_registry.call_tool(name, args)
        ok = not (isinstance(result, dict) and result.get("success") is False)
        record_tool_timing(name, (time.perf_counter() - t_tool) * 1000.0, ok)
        obs = await asyncio.to_thread(
            partial(
                format_tool_result_for_llm,
                name,
                f"compat_{iteration}_{name}",
                result,
                run_tag=run_tag_c,
            )
        )
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


async def _iter_native_react(
    messages: list[dict[str, Any]],
    deps: AgentDeps,
) -> AsyncIterator[dict[str, Any]]:
    if not deps.tool_registry:
        raise RuntimeError("no tool registry")

    objs, allowed_names = filter_tools_for_agent(
        deps.tool_registry,
        allow_tools=deps.tool_allow_tools,
        deny_tools=deps.tool_deny_tools,
        allow_categories=deps.tool_allow_categories,
        max_tier=deps.tool_max_tier,
        max_tools=deps.max_tools,
    )
    openai_tools = [t.definition.to_openai_format() for t in objs]
    allowed_set = set(allowed_names)

    dialog = _merge_system_instruction(_sanitize_dialog_messages(list(messages)))
    logger.debug(
        "[agent.native] registry_tools=%s visible_tools=%s",
        len(deps.tool_registry.list_tools()) if deps.tool_registry else 0,
        len(allowed_names),
    )
    if openai_tools:
        _inject_tool_manifest(dialog, allowed_names)
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
        text = await deps.call_llm(
            f"{get_native_system_prefix()}\n\nUser request:\n{q}\n\nAnswer without tools."
        )
        yield {"type": "final", "content": text.strip()}
        return

    last_sig = ""
    same_sig_count = 0
    fail_streak = 0
    run_tag = secrets.token_hex(6)
    budget_used = 0
    cap_ceiling = cumulative_budget_limit()
    ctx_window = effective_context_window_tokens(deps.model)

    for iteration in range(deps.max_steps):
        if _aborted(deps):
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
            tool_calls = []

            while True:
                if _aborted(deps):
                    yield {"type": "final", "content": "（对话已由用户中断）"}
                    return
                resp = await deps.chat_with_tools(dialog, openai_tools)
                raw_msg, tool_calls = _parse_openai_completion(resp)
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
                    yield {"type": "status", "phase": "answer", "detail": "输出预算已达上限"}
                    yield {
                        "type": "final",
                        "content": out or "Stopped: cumulative completion-token budget exhausted.",
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
                if fr in ("length", "max_tokens") and cont_i < max_len_cont:
                    yield {
                        "type": "status",
                        "phase": "llm",
                        "iteration": iteration,
                        "detail": f"输出因长度截断，续写 ({cont_i + 1}/{max_len_cont})",
                    }
                    dialog.append(_assistant_turn_from_response(raw_msg))
                    dialog.append({"role": "user", "content": _length_continuation_user_text()})
                    cont_i += 1
                    continue

                yield {"type": "status", "phase": "answer", "detail": "模型返回最终回答"}
                yield {"type": "final", "content": out or "No response."}
                return

            dialog.append(_assistant_turn_from_response(raw_msg))

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

        for idx, tc in enumerate(tool_calls):
            name = tc["name"]
            raw_args = tc.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                if not isinstance(args, dict):
                    args = {}
            except json.JSONDecodeError:
                args = {}

            tcid = tc.get("id") or f"call_{iteration}_{idx}_{name}"
            yield {
                "type": "tool_start",
                "tool": name,
                "call_id": str(tcid),
                "iteration": iteration,
                "args_preview": _preview_json(args, limit=1200),
            }

            t_tool = time.perf_counter()
            if allowed_set and name not in allowed_set:
                result = {"success": False, "error": f"Tool not allowed: {name}"}
            else:
                try:
                    result = await deps.tool_registry.call_tool(name, args)
                except Exception as e:
                    logger.error("[agent.native] tool %s failed: %s", name, e)
                    result = {"success": False, "error": str(e)}

            ok = not (isinstance(result, dict) and result.get("success") is False)
            record_tool_timing(name, (time.perf_counter() - t_tool) * 1000.0, ok)
            tool_body = await asyncio.to_thread(
                partial(format_tool_result_for_llm, name, str(tcid), result, run_tag=run_tag)
            )
            preview = tool_body if len(tool_body) <= 2000 else tool_body[:1999] + "…"
            yield {
                "type": "tool_done",
                "tool": name,
                "call_id": str(tcid),
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

            if same_sig_count >= deps.loop_max_repeat_same_tool:
                yield {"type": "final", "content": "Stopped: repeated identical tool calls."}
                return
            if fail_streak >= deps.loop_max_consecutive_tool_failures:
                yield {"type": "final", "content": "Stopped: too many consecutive tool failures."}
                return

            dialog.append(
                {
                    "role": "tool",
                    "tool_call_id": str(tcid),
                    "content": tool_body,
                }
            )

    yield {"type": "final", "content": "Maximum steps reached."}


def _extract_text(messages: list[dict[str, Any]]) -> str:
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


def _compact_tools(raw_tools: list[dict]) -> list[dict]:
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


def _build_decision_prompt(question: str, tools: list[dict], scratchpad: str) -> str:
    return build_plan_decision_prompt(question=question, tools=tools, scratchpad=scratchpad)


def _extract_json_obj(text: str) -> dict[str, Any]:
    if not text:
        raise ValueError("empty model output")
    text = text.strip()

    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE)
    if m:
        text = m.group(1).strip()

    if not text.startswith("{"):
        m2 = re.search(r"(\{[\s\S]*\})", text)
        if m2:
            text = m2.group(1)

    return json.loads(text)


def _validate_decision(obj: dict[str, Any], tool_names: list[str]) -> tuple[str, dict[str, Any]]:
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


async def _plan_node(state: AgentState, deps: AgentDeps) -> AgentState:
    question = _extract_text(state.get("messages", []))
    if not question:
        return {"decision": {"kind": "final", "final": "No question provided."}}

    tools = []
    tool_names = []

    if deps.use_tools and deps.tool_registry:
        try:
            objs, _ = filter_tools_for_agent(
                deps.tool_registry,
                allow_tools=deps.tool_allow_tools,
                deny_tools=deps.tool_deny_tools,
                allow_categories=deps.tool_allow_categories,
                max_tier=deps.tool_max_tier,
                max_tools=deps.max_tools,
            )
            raw_tools = list_tools_payload(objs)
            tools = _compact_tools(raw_tools)
            tool_names = [t["name"] for t in tools]
        except Exception as e:
            logger.warning(f"[agent.plan] Failed to get tools: {e}")

    prompt = _build_decision_prompt(question, tools, state.get("scratchpad", ""))

    try:
        text = (await deps.call_llm(prompt)).strip()
        obj = _extract_json_obj(text)
        kind, payload = _validate_decision(obj, tool_names)
        return {"decision": {"kind": kind, **payload}}
    except Exception as e:
        logger.error(f"[agent.plan] Failed: {e}")
        return {"decision": {"kind": "final", "final": f"Processing failed: {str(e)[:100]}"}}


async def _act_node(state: AgentState, deps: AgentDeps) -> AgentState:
    decision = state.get("decision", {})
    if decision.get("kind") != "tool":
        return {}

    name = decision.get("name")
    args = decision.get("args", {})

    if not deps.tool_registry:
        return {
            "scratchpad": state.get("scratchpad", "") + "\n[ERROR] No tool registry available",
            "error": "No tool registry",
        }

    try:
        result = await deps.tool_registry.call_tool(name, args)

        sig = json.dumps({"name": name, "args": args}, sort_keys=True, ensure_ascii=False)
        prev_sig = str(state.get("last_tool_signature") or "")
        repeat = int(state.get("repeat_tool_calls") or 0)
        repeat = repeat + 1 if sig == prev_sig else 1

        fail_streak = int(state.get("tool_fail_streak") or 0)
        if isinstance(result, dict) and result.get("success") is False:
            fail_streak += 1
        else:
            fail_streak = 0

        scratch = state.get("scratchpad", "")
        rt = secrets.token_hex(5)
        obs = await asyncio.to_thread(
            partial(format_tool_result_for_llm, str(name), f"lg_{name}_{rt}", result, run_tag=rt)
        )
        scratch += f"\nCALL {name} args={json.dumps(args, ensure_ascii=False)}\nOBS {obs}\n"

        return {
            "scratchpad": scratch,
            "last_tool": name,
            "last_result": result,
            "tool_results": state.get("tool_results", []) + [{"tool": name, "result": result}],
            "last_tool_signature": sig,
            "repeat_tool_calls": repeat,
            "tool_fail_streak": fail_streak,
        }
    except Exception as e:
        logger.error(f"[agent.act] Tool {name} failed: {e}")
        sig = json.dumps({"name": name, "args": args}, sort_keys=True, ensure_ascii=False)
        prev_sig = str(state.get("last_tool_signature") or "")
        repeat = int(state.get("repeat_tool_calls") or 0)
        repeat = repeat + 1 if sig == prev_sig else 1
        fail_streak = int(state.get("tool_fail_streak") or 0) + 1
        return {
            "scratchpad": state.get("scratchpad", "") + f"\n[ERROR] {name}: {str(e)}",
            "error": str(e),
            "last_tool": name,
            "last_tool_signature": sig,
            "repeat_tool_calls": repeat,
            "tool_fail_streak": fail_streak,
        }


def _route_decision(state: AgentState) -> str:
    decision = state.get("decision", {})
    kind = decision.get("kind")

    if kind == "tool":
        return "act"
    return "final"


async def _check_steps(state: AgentState, deps: AgentDeps) -> AgentState:
    steps = int(state.get("steps", 0)) + 1
    updates: AgentState = {"steps": steps}

    if steps >= deps.max_steps:
        updates["decision"] = {"kind": "final", "final": "Maximum steps reached."}
        return updates

    rep = int(state.get("repeat_tool_calls") or 0)
    if rep >= deps.loop_max_repeat_same_tool:
        updates["decision"] = {
            "kind": "final",
            "final": "Stopped: repeated identical tool calls.",
        }
        return updates

    fs = int(state.get("tool_fail_streak") or 0)
    if fs >= deps.loop_max_consecutive_tool_failures:
        updates["decision"] = {
            "kind": "final",
            "final": "Stopped: too many consecutive tool failures.",
        }
        return updates

    scratch = state.get("scratchpad") or ""
    if deps.scratchpad_compress_enabled and len(scratch) > deps.scratchpad_max_chars:
        task = _extract_text(state.get("messages", []))
        updates["scratchpad"] = await compress_scratchpad(
            deps,
            scratchpad=scratch,
            task_hint=task,
            target_chars=deps.scratchpad_compress_target_chars,
        )

    return updates


def _route_after_check(state: AgentState) -> str:
    decision = state.get("decision", {})
    if decision.get("kind") == "final":
        return "final"
    return "plan"


def build_react_graph(deps: AgentDeps) -> StateGraph:
    async def plan_node(state: AgentState) -> AgentState:
        return await _plan_node(state, deps)

    async def act_node(state: AgentState) -> AgentState:
        return await _act_node(state, deps)

    async def check_steps_node(state: AgentState) -> AgentState:
        return await _check_steps(state, deps)

    graph = StateGraph(AgentState)

    graph.add_node("plan", plan_node)
    graph.add_node("act", act_node)
    graph.add_node("check_steps", check_steps_node)

    graph.set_entry_point("plan")
    graph.add_conditional_edges("plan", _route_decision, {"act": "act", "final": END})
    graph.add_edge("act", "check_steps")
    graph.add_conditional_edges("check_steps", _route_after_check, {"plan": "plan", "final": END})

    return graph


class ReactAgent:
    def __init__(self, deps: AgentDeps | None = None, **kwargs):
        if deps is None:
            deps = create_agent_deps(**kwargs)
        self.deps = deps
        self.graph = build_react_graph(deps)
        self.app = self.graph.compile()

    async def _run_legacy(self, messages: list[dict[str, Any]]) -> str:
        init = create_initial_state(messages)
        current_state = dict(init)
        async for chunk in self.app.astream(init):
            for node_name, node_output in chunk.items():
                if isinstance(node_output, dict):
                    if "decision" in node_output:
                        logger.debug(f"[agent] {node_name}: {node_output['decision']}")
                    current_state.update(node_output)
        decision = current_state.get("decision")
        if not decision or not isinstance(decision, dict):
            return "Agent produced no valid decision."
        if decision.get("kind") == "final":
            return str(decision.get("final") or "")
        return str(decision.get("final") or "No response generated.")

    async def run(self, messages: list[dict[str, Any]]) -> str:
        mode = (self.deps.tool_call_mode or "auto").strip().lower()
        if mode == "compat" and self.deps.use_tools and not self.deps._custom_llm_call:
            text_out = ""
            async for ev in _iter_compat_react(messages, self.deps):
                if isinstance(ev, dict) and ev.get("type") == "final":
                    text_out = str(ev.get("content") or "")
            return text_out or ""

        if (
            _auto_use_compat_first_for_mcp(self.deps)
            and self.deps.use_tools
            and not self.deps._custom_llm_call
        ):
            text_out = ""
            async for ev in _iter_compat_react(messages, self.deps):
                if isinstance(ev, dict) and ev.get("type") == "final":
                    text_out = str(ev.get("content") or "")
            return text_out or ""

        if (
            mode in ("auto", "native")
            and self.deps.native_tool_calls
            and self.deps.use_tools
            and not self.deps._custom_llm_call
        ):
            try:
                text_out = ""
                saw_tool = False
                async for ev in _iter_native_react(messages, self.deps):
                    if isinstance(ev, dict) and ev.get("type") == "tool_start":
                        saw_tool = True
                    if isinstance(ev, dict) and ev.get("type") == "final":
                        text_out = str(ev.get("content") or "")
                if not saw_tool and _looks_tool_blind_response(text_out):
                    logger.warning(
                        "[agent] native tool-calling appears tool-blind; fallback to legacy ReAct"
                    )
                    if mode == "auto":
                        logger.warning("[agent] switching to compat tool loop")
                        async for ev in _iter_compat_react(messages, self.deps):
                            if isinstance(ev, dict) and ev.get("type") == "final":
                                return str(ev.get("content") or "")
                    return await self._run_legacy(messages)
                return text_out or ""
            except Exception as e:
                logger.warning("[agent] native ReAct unavailable, using legacy graph: %s", e)
        return await self._run_legacy(messages)

    async def run_stream(self, messages: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
        mode = (self.deps.tool_call_mode or "auto").strip().lower()
        if mode == "compat" and self.deps.use_tools and not self.deps._custom_llm_call:
            async for ev in _iter_compat_react(messages, self.deps):
                yield ev
            return

        if (
            _auto_use_compat_first_for_mcp(self.deps)
            and self.deps.use_tools
            and not self.deps._custom_llm_call
        ):
            async for ev in _iter_compat_react(messages, self.deps):
                yield ev
            return

        if (
            mode in ("auto", "native")
            and self.deps.native_tool_calls
            and self.deps.use_tools
            and not self.deps._custom_llm_call
        ):
            try:
                buffered: list[dict[str, Any]] = []
                saw_tool = False
                final_text = ""
                async for ev in _iter_native_react(messages, self.deps):
                    if isinstance(ev, dict) and ev.get("type") == "tool_start":
                        saw_tool = True
                    if isinstance(ev, dict) and ev.get("type") == "final":
                        final_text = str(ev.get("content") or "")
                    buffered.append(ev)
                if not saw_tool and _looks_tool_blind_response(final_text):
                    logger.warning(
                        "[agent] native stream tool-blind; fallback to legacy ReAct stream"
                    )
                    if mode == "auto":
                        logger.warning("[agent] switching to compat tool loop (stream)")
                        async for ev in _iter_compat_react(messages, self.deps):
                            yield ev
                        return
                else:
                    for ev in buffered:
                        yield ev
                    return
            except Exception as e:
                logger.warning("[agent] native ReAct stream fallback: %s", e)

        init = create_initial_state(messages)

        async for chunk in self.app.astream(init):
            if _aborted(self.deps):
                yield {"type": "final", "content": "（对话已由用户中断）"}
                return
            for node_name, node_output in chunk.items():
                yield {"type": "node", "node": node_name, "data": node_output}

                if isinstance(node_output, dict) and "decision" in node_output:
                    decision = node_output["decision"]
                    if decision.get("kind") == "final":
                        yield {"type": "final", "content": decision.get("final", "")}
                        return
