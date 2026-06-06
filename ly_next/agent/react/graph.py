"""LangGraph builder for legacy plan-act ReAct mode."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from ly_next.agent.deps import AgentDeps
from ly_next.agent.react.nodes import (
    act_node,
    check_steps_node,
    plan_node,
    route_after_check,
    route_decision,
)
from ly_next.agent.state import AgentState


def build_react_graph(deps: AgentDeps) -> StateGraph:
    async def plan(state: AgentState) -> AgentState:
        return await plan_node(state, deps)

    async def act(state: AgentState) -> AgentState:
        return await act_node(state, deps)

    async def check_steps(state: AgentState) -> AgentState:
        return await check_steps_node(state, deps)

    graph = StateGraph(AgentState)
    graph.add_node("plan", plan)
    graph.add_node("act", act)
    graph.add_node("check_steps", check_steps)
    graph.set_entry_point("plan")
    graph.add_conditional_edges("plan", route_decision, {"act": "act", "final": END})
    graph.add_edge("act", "check_steps")
    graph.add_conditional_edges("check_steps", route_after_check, {"plan": "plan", "final": END})
    return graph
