"""ReAct Agent."""

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from langgraph.graph import END, StateGraph

from ly_next.agent.deps import AgentDeps, create_agent_deps
from ly_next.agent.scratchpad_compress import compress_scratchpad
from ly_next.agent.state import AgentState, create_initial_state
from ly_next.agent.tool_filter import filter_tools_for_agent, list_tools_payload
from ly_next.core.logger import get_logger

logger = get_logger(__name__)


def _extract_text(messages: list[dict[str, Any]]) -> str:
    """Extract text from messages."""
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
    """Compact tool list for LLM context."""
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
    """Build prompt for LLM decision making."""
    tools_desc = (
        "\n".join([f"- {t['name']}: {t['description']}" for t in tools]) if tools else "(no tools)"
    )
    tool_names = ", ".join([t["name"] for t in tools]) if tools else ""

    return f"""You are a tool orchestration AI. Your goal is to solve the problem in minimum steps.

Available tools:
{tools_desc}

Output only JSON (no extra text).

When you need to call a tool:
{{"type":"tool","name":"<tool_name>","args":{{...}}}}

When you can answer directly:
{{"type":"final","final":"..."}}

Constraints:
- Only choose from these tools: {tool_names}
- args must be JSON object
- If a tool returns success=false, try a different approach

Question:
{question}

Known process (for reference, don't repeat):
{scratchpad}"""


def _extract_json_obj(text: str) -> dict[str, Any]:
    """Extract JSON object from model output."""
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
    """Validate LLM decision."""
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
    """Plan node: Call LLM for decision."""
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
    """Act node: Execute tool call."""
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
        scratch += f"\nCALL {name} args={json.dumps(args, ensure_ascii=False)}\nOBS {json.dumps(result, ensure_ascii=False)}\n"

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
    """Route based on decision type."""
    decision = state.get("decision", {})
    kind = decision.get("kind")

    if kind == "tool":
        return "act"
    return "final"


async def _check_steps(state: AgentState, deps: AgentDeps) -> AgentState:
    """Check and increment step count."""
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
    """Route after step check."""
    decision = state.get("decision", {})
    if decision.get("kind") == "final":
        return "final"
    return "plan"


def build_react_graph(deps: AgentDeps) -> StateGraph:
    """Build ReAct agent graph."""

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
    """ReAct (Reasoning + Acting) Agent."""

    def __init__(self, deps: AgentDeps | None = None, **kwargs):
        if deps is None:
            deps = create_agent_deps(**kwargs)
        self.deps = deps
        self.graph = build_react_graph(deps)
        self.app = self.graph.compile()

    async def run(self, messages: list[dict[str, Any]]) -> str:
        """Run agent with messages."""
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

        kind = decision.get("kind")
        if kind == "final":
            return str(decision.get("final") or "")

        return str(decision.get("final") or "No response generated.")

    async def run_stream(self, messages: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
        """Run agent with streaming."""
        init = create_initial_state(messages)

        async for chunk in self.app.astream(init):
            for node_name, node_output in chunk.items():
                yield {"type": "node", "node": node_name, "data": node_output}

                if isinstance(node_output, dict) and "decision" in node_output:
                    decision = node_output["decision"]
                    if decision.get("kind") == "final":
                        yield {"type": "final", "content": decision.get("final", "")}
                        return
