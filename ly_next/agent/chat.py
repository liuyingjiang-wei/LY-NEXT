from collections.abc import AsyncIterator
from typing import Any

from ly_next.agent.deps import AgentDeps, create_agent_deps
from ly_next.core.logger import get_logger

logger = get_logger(__name__)


class ChatAgent:
    def __init__(self, deps: AgentDeps | None = None, **kwargs):
        if deps is None:
            deps = create_agent_deps(**kwargs)
        self.deps = deps

    async def run(self, messages: list[dict[str, Any]]) -> str:
        if not messages:
            return "No messages provided."

        processed_messages = self._process_messages(messages)
        prompt = self._build_prompt(processed_messages)

        try:
            response = await self.deps.call_llm(prompt)
            return response
        except Exception as e:
            logger.error(f"[chat] LLM call failed: {e}")
            return f"Error: {str(e)}"

    async def run_stream(self, messages: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
        if not messages:
            yield {"type": "error", "content": "No messages provided."}
            return

        processed_messages = self._process_messages(messages)
        prompt = self._build_prompt(processed_messages)

        try:
            full_response = ""
            async for chunk in self.deps.call_llm_stream(prompt):
                full_response += chunk
                yield {"type": "chunk", "content": chunk}

            yield {"type": "final", "content": full_response}
        except Exception as e:
            logger.error(f"[chat] Stream failed: {e}")
            yield {"type": "error", "content": str(e)}

    def _process_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        processed = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if not content:
                continue

            if role == "system":
                processed.append({"role": "system", "content": content})
            elif role in ("user", "assistant"):
                processed.append({"role": role, "content": content})
            else:
                processed.append({"role": "user", "content": content})

        return processed

    def _build_prompt(self, messages: list[dict[str, Any]]) -> str:
        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            parts.append(f"{role.upper()}: {content}")
        return "\n\n".join(parts)
