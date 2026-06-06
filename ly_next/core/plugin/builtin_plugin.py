"""Built-in official plugin: core tools, agents, and LLM providers."""

from __future__ import annotations

from ly_next.agent.chat import ChatAgent
from ly_next.agent.coordinator import CoordinatorAgent
from ly_next.agent.factory import AgentFactory
from ly_next.agent.plan import PlanAgent
from ly_next.agent.react import ReactAgent
from ly_next.core.app_context import AppContext
from ly_next.core.plugin.protocol import LyNextPlugin
from ly_next.tools.builtin import register_builtin_tools
from ly_next.tools.registry import ToolRegistry


class BuiltinPlugin(LyNextPlugin):
    name = "ly-next-builtin"
    version = "1.0.0"
    description = "Core built-in tools and agent modes"

    def register_tools(self, registry: ToolRegistry, ctx: AppContext) -> None:
        n = register_builtin_tools(registry)
        ctx.extras["builtin_tools_registered"] = n

    def register_agents(self, factory: AgentFactory, ctx: AppContext) -> None:
        factory.register_agent_type("react", ReactAgent)
        factory.register_agent_type("plan", PlanAgent)
        factory.register_agent_type("chat", ChatAgent)
        factory.register_agent_type("coordinator", CoordinatorAgent)
