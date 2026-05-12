import asyncio
import json
import re
import secrets
from collections.abc import AsyncIterator
from functools import partial
from typing import Any

from langgraph.graph import END, StateGraph

from ly_next.agent.deps import AgentDeps, create_agent_deps
from ly_next.agent.prompt_augment import last_user_query
from ly_next.agent.scratchpad_compress import compress_scratchpad
from ly_next.agent.state import AgentState, create_initial_state
from ly_next.agent.tool_filter import filter_tools_for_agent, list_tools_payload
from ly_next.core.logger import get_logger
from ly_next.core.tool_result_spill import format_tool_result_for_llm

logger = get_logger(__name__)


async def _plan_phase(state: AgentState, deps: AgentDeps) -> AgentState:
    msgs = state.get("messages") or []
    question = last_user_query(msgs)
    if not question and msgs:
        c0 = msgs[0].get("content", "")
        question = c0 if isinstance(c0, str) else json.dumps(c0, ensure_ascii=False)
    if not question:
        return {"plan": [], "error": "No question provided"}

    tools = []
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
            for t in list_tools_payload(objs):
                tools.append({"name": t.get("name", ""), "description": t.get("description", "")})
        except Exception as e:
            logger.warning(f"[plan] Failed to get tools: {e}")

    tools_desc = (
        "\n".join([f"- {t['name']}: {t['description']}" for t in tools]) if tools else "(no tools)"
    )

    prompt = f"""Break down the following task into numbered steps.
For each step, specify if it requires a tool call or can be done directly.

Available tools: {tools_desc}

Task: {question}

Output JSON:
{{"steps": [
  {{"id": 1, "action": "call_tool" or "answer", "tool": "tool_name" or null, "args": {{}} or null, "description": "what this step does", "answer": "direct reply text when action is answer"}},
  ...
]}}"""

    try:
        text = (await deps.call_llm(prompt)).strip()
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE)
        if m:
            text = m.group(1).strip()
        if not text.startswith("{"):
            m2 = re.search(r"(\{[\s\S]*\})", text)
            if m2:
                text = m2.group(1)

        plan_data = json.loads(text)
        plan = plan_data.get("steps", [])

        return {
            "plan": plan,
            "current_step": 0,
            "plan_results": [],
        }
    except Exception as e:
        logger.error(f"[plan] Planning failed: {e}")
        return {"plan": [], "error": str(e)}


async def _execute_step(state: AgentState, deps: AgentDeps) -> AgentState:
    plan = state.get("plan", [])
    current_step = state.get("current_step", 0)

    if current_step >= len(plan):
        return {"done": True}

    step = plan[current_step]
    action = step.get("action", "")

    if action == "answer":
        raw_ans = step.get("answer") or step.get("description") or ""
        text = (raw_ans.strip() if isinstance(raw_ans, str) else str(raw_ans).strip()) or "Done"
        return {
            "done": True,
            "final_response": text,
        }

    if action == "call_tool" and deps.tool_registry:
        tool_name = step.get("tool")
        args = step.get("args", {})

        if not tool_name:
            return {"error": f"Step {current_step + 1}: No tool specified"}

        try:
            result = await deps.tool_registry.call_tool(tool_name, args)
            sig = json.dumps({"name": tool_name, "args": args}, sort_keys=True, ensure_ascii=False)
            prev_sig = str(state.get("last_tool_signature") or "")
            repeat = int(state.get("repeat_tool_calls") or 0)
            repeat = repeat + 1 if sig == prev_sig else 1

            fail_streak = int(state.get("tool_fail_streak") or 0)
            if isinstance(result, dict) and result.get("success") is False:
                fail_streak += 1
            else:
                fail_streak = 0

            plan_results = state.get("plan_results", [])
            plan_results.append(
                {
                    "step": current_step + 1,
                    "tool": tool_name,
                    "args": args,
                    "result": result,
                }
            )
            rt = secrets.token_hex(5)
            obs = await asyncio.to_thread(
                partial(
                    format_tool_result_for_llm,
                    str(tool_name),
                    f"plan_{current_step}_{rt}",
                    result,
                    run_tag=rt,
                )
            )
            return {
                "current_step": current_step + 1,
                "plan_results": plan_results,
                "scratchpad": state.get("scratchpad", "")
                + f"\n[Step {current_step + 1}] {tool_name}: {obs}",
                "last_tool_signature": sig,
                "repeat_tool_calls": repeat,
                "tool_fail_streak": fail_streak,
            }
        except Exception as e:
            logger.error(f"[execute] Step {current_step + 1} failed: {e}")
            sig = json.dumps({"name": tool_name, "args": args}, sort_keys=True, ensure_ascii=False)
            prev_sig = str(state.get("last_tool_signature") or "")
            repeat = int(state.get("repeat_tool_calls") or 0)
            repeat = repeat + 1 if sig == prev_sig else 1
            fail_streak = int(state.get("tool_fail_streak") or 0) + 1
            return {
                "error": f"Step {current_step + 1}: {str(e)}",
                "last_tool_signature": sig,
                "repeat_tool_calls": repeat,
                "tool_fail_streak": fail_streak,
            }

    return {"current_step": current_step + 1}


async def _check_plan(state: AgentState, deps: AgentDeps) -> AgentState:
    plan = state.get("plan", [])
    current_step = state.get("current_step", 0)
    done = state.get("done", False)
    error = state.get("error", "")
    steps = state.get("steps", 0) + 1

    if int(state.get("repeat_tool_calls") or 0) >= deps.loop_max_repeat_same_tool:
        return {"done": True, "final_response": "Stopped: repeated identical tool calls."}

    if int(state.get("tool_fail_streak") or 0) >= deps.loop_max_consecutive_tool_failures:
        return {"done": True, "final_response": "Stopped: too many consecutive tool failures."}

    if steps >= deps.max_steps:
        return {"done": True, "final_response": "Maximum steps reached."}

    if done or current_step >= len(plan):
        if not state.get("final_response"):
            plan_list = state.get("plan") or []
            plan_results = state.get("plan_results", [])
            plan_err = state.get("error")
            if plan_err and not plan_list:
                return {"final_response": f"Error: {plan_err}", "steps": steps, "done": True}

            question = last_user_query(state.get("messages") or [])
            if not question:
                m0 = (state.get("messages") or [{}])[0].get("content", "")
                question = m0 if isinstance(m0, str) else json.dumps(m0, ensure_ascii=False)

            prompt = f"""Based on the following step results, provide a final answer to the user's question.

Question: {question}

Step Results:
{json.dumps(plan_results, ensure_ascii=False, indent=2)}

Output only JSON:
{{"answer": "your final answer here"}}"""

            try:
                text = (await deps.call_llm(prompt)).strip()
                m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE)
                if m:
                    text = m.group(1).strip()
                if not text.startswith("{"):
                    m2 = re.search(r"(\{[\s\S]*\})", text)
                    if m2:
                        text = m2.group(1)
                data = json.loads(text)
                return {
                    "final_response": data.get("answer", "Done"),
                    "steps": steps,
                    "done": True,
                }
            except Exception as e:
                return {
                    "final_response": "Completed with some errors.",
                    "steps": steps,
                    "error": str(e),
                    "done": True,
                }

        return {"done": True, "steps": steps}

    if error:
        return {"done": True, "final_response": f"Error: {error}"}

    scratch = state.get("scratchpad") or ""
    if deps.scratchpad_compress_enabled and len(scratch) > deps.scratchpad_max_chars:
        question = (
            state.get("messages", [{}])[0].get("content", "") if state.get("messages") else ""
        )
        if isinstance(question, dict):
            question = json.dumps(question, ensure_ascii=False)
        new_sp = await compress_scratchpad(
            deps,
            scratchpad=scratch,
            task_hint=str(question or ""),
            target_chars=deps.scratchpad_compress_target_chars,
        )
        return {"done": False, "steps": steps, "scratchpad": new_sp}

    return {"done": False, "steps": steps}


def _route_after_check(state: AgentState) -> str:
    if state.get("done", False):
        return END
    return "execute"


def build_plan_agent_graph(deps: AgentDeps) -> StateGraph:
    async def plan_node(state: AgentState) -> AgentState:
        return await _plan_phase(state, deps)

    async def execute_node(state: AgentState) -> AgentState:
        return await _execute_step(state, deps)

    async def check_node(state: AgentState) -> AgentState:
        return await _check_plan(state, deps)

    graph = StateGraph(AgentState)

    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_node("check", check_node)

    graph.set_entry_point("plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "check")
    graph.add_conditional_edges("check", _route_after_check, {END: END, "execute": "execute"})

    return graph


class PlanAgent:
    def __init__(self, deps: AgentDeps | None = None, **kwargs):
        if deps is None:
            deps = create_agent_deps(**kwargs)
        self.deps = deps
        self.graph = build_plan_agent_graph(deps)
        self.app = self.graph.compile()

    async def run(self, messages: list[dict[str, Any]]) -> str:
        init = create_initial_state(messages)

        final_state = {}
        async for chunk in self.app.astream(init):
            for _node_name, node_output in chunk.items():
                final_state.update(node_output)

        return final_state.get("final_response", "No response generated.")

    async def run_stream(self, messages: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
        init = create_initial_state(messages)

        async for chunk in self.app.astream(init):
            if self.deps.stop_event and self.deps.stop_event.is_set():
                yield {"type": "final", "content": "（对话已由用户中断）"}
                return
            for node_name, node_output in chunk.items():
                yield {"type": "node", "node": node_name, "data": node_output}

                if node_output.get("final_response"):
                    yield {"type": "final", "content": node_output["final_response"]}
                    return
