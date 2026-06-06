"""LangGraph node implementations for legacy ReAct graph mode."""

from __future__ import annotations

import json
import secrets

from ly_next.agent.deps import AgentDeps
from ly_next.agent.json_extract import parse_json_object
from ly_next.agent.prompt_templates import build_plan_decision_prompt
from ly_next.agent.react.helpers import (
    compact_tools,
    extract_text,
    run_tool_with_obs,
    validate_decision,
)
from ly_next.agent.scratchpad_compress import compress_scratchpad
from ly_next.agent.state import AgentState
from ly_next.agent.tool_filter import get_filtered_tools_for_deps, list_tools_payload
from ly_next.agent.tool_streak import streak_after_tool_call, streak_after_tool_error
from ly_next.core.logger import get_logger

logger = get_logger(__name__)


def build_decision_prompt(question: str, tools: list[dict], scratchpad: str) -> str:
    return build_plan_decision_prompt(question=question, tools=tools, scratchpad=scratchpad)


async def plan_node(state: AgentState, deps: AgentDeps) -> AgentState:
    question = extract_text(state.get("messages", []))
    if not question:
        return {"decision": {"kind": "final", "final": "No question provided."}}

    tools: list[dict] = []
    tool_names: list[str] = []

    if deps.use_tools and deps.tool_registry:
        try:
            objs, _ = get_filtered_tools_for_deps(deps)
            raw_tools = list_tools_payload(objs)
            tools = compact_tools(raw_tools)
            tool_names = [t["name"] for t in tools]
        except Exception as e:
            logger.warning("[agent.plan] Failed to get tools: %s", e)

    prompt = build_decision_prompt(question, tools, state.get("scratchpad", ""))

    try:
        text = (await deps.call_llm(prompt)).strip()
        obj = parse_json_object(text)
        kind, payload = validate_decision(obj, tool_names)
        return {"decision": {"kind": kind, **payload}}
    except Exception as e:
        logger.error("[agent.plan] Failed: %s", e)
        return {"decision": {"kind": "final", "final": f"Processing failed: {str(e)[:100]}"}}


async def act_node(state: AgentState, deps: AgentDeps) -> AgentState:
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
        result, obs = await run_tool_with_obs(
            deps,
            str(name),
            args if isinstance(args, dict) else {},
            call_id=f"lg_{name}_{secrets.token_hex(5)}",
            run_tag=secrets.token_hex(5),
        )
        streak = streak_after_tool_call(state, name, args, result)

        scratch = state.get("scratchpad", "")
        scratch += f"\nCALL {name} args={json.dumps(args, ensure_ascii=False)}\nOBS {obs}\n"
        tool_row = {"tool": name, "result": result}

        return {
            "scratchpad": scratch,
            "last_tool": name,
            "last_result": result,
            "tool_results": state.get("tool_results", []) + [tool_row],
            **streak,
        }
    except Exception as e:
        logger.error("[agent.act] Tool %s failed: %s", name, e)
        streak = streak_after_tool_error(state, name, args)
        return {
            "scratchpad": state.get("scratchpad", "") + f"\n[ERROR] {name}: {str(e)}",
            "error": str(e),
            "last_tool": name,
            **streak,
        }


def route_decision(state: AgentState) -> str:
    decision = state.get("decision", {})
    if decision.get("kind") == "tool":
        return "act"
    return "final"


async def check_steps_node(state: AgentState, deps: AgentDeps) -> AgentState:
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
        task = extract_text(state.get("messages", []))
        updates["scratchpad"] = await compress_scratchpad(
            deps,
            scratchpad=scratch,
            task_hint=task,
            target_chars=deps.scratchpad_compress_target_chars,
        )

    return updates


def route_after_check(state: AgentState) -> str:
    decision = state.get("decision", {})
    if decision.get("kind") == "final":
        return "final"
    return "plan"
