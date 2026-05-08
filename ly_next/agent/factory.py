from typing import Any

from ly_next.agent.chat import ChatAgent
from ly_next.agent.deps import AgentDeps, create_agent_deps
from ly_next.agent.plan import PlanAgent
from ly_next.agent.prompt_augment import augment_messages_async
from ly_next.agent.react import ReactAgent
from ly_next.core.config import config
from ly_next.core.logger import get_logger

logger = get_logger(__name__)


class AgentFactory:
    _agent_types: dict[str, type] = {
        "react": ReactAgent,
        "plan": PlanAgent,
        "chat": ChatAgent,
    }

    @classmethod
    def register_agent_type(cls, name: str, agent_class: type) -> None:
        cls._agent_types[name.lower()] = agent_class
        logger.info(f"Registered agent type: {name}")

    @classmethod
    def list_agent_types(cls) -> list[str]:
        return list(cls._agent_types.keys())

    @classmethod
    def create_agent(cls, mode: str | None = None, **kwargs) -> Any:
        mode = mode or config.get("agent.reasoning_mode", "react")
        mode = mode.lower()

        if mode not in cls._agent_types:
            raise ValueError(f"Unknown agent mode: {mode}. Available: {cls.list_agent_types()}")

        agent_class = cls._agent_types[mode]
        deps = kwargs.pop("deps", None)
        if isinstance(deps, AgentDeps):
            return agent_class(deps)
        deps = create_agent_deps(**kwargs)

        return agent_class(deps)

    @classmethod
    def create_react_agent(cls, **kwargs) -> ReactAgent:
        deps = create_agent_deps(**kwargs)
        return ReactAgent(deps)

    @classmethod
    def create_plan_agent(cls, **kwargs) -> PlanAgent:
        deps = create_agent_deps(**kwargs)
        return PlanAgent(deps)

    @classmethod
    def create_chat_agent(cls, **kwargs) -> ChatAgent:
        deps = create_agent_deps(**kwargs)
        return ChatAgent(deps)

    @classmethod
    async def run_agent(
        cls,
        messages: list[dict[str, Any]],
        mode: str | None = None,
        stream: bool = False,
        **kwargs,
    ) -> Any:
        messages = await augment_messages_async(list(messages))
        agent = cls.create_agent(mode=mode, **kwargs)

        if stream:
            return agent.run_stream(messages)

        return await agent.run(messages)
