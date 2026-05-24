from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, suppress
from typing import Any

from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.core.thread_persistence import db_available

logger = get_logger(__name__)

_checkpointer: Any | None = None
_exit_stack: AsyncExitStack | None = None


def checkpoint_enabled() -> bool:
    return bool(config.get("agent.persistence.checkpoint.enabled", True))


def checkpoint_active() -> bool:
    return checkpoint_enabled() and _checkpointer is not None


async def init_checkpointer() -> None:
    global _checkpointer, _exit_stack

    if not checkpoint_enabled():
        logger.info("LangGraph checkpoint disabled by config")
        return
    if _checkpointer is not None:
        return

    backend = str(config.get("agent.persistence.checkpoint.backend", "postgres")).strip().lower()
    if backend == "postgres" and db_available():
        stack = AsyncExitStack()
        await stack.__aenter__()
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            dsn = config.iter_asyncpg_dsn()[0]
            saver = await stack.enter_async_context(AsyncPostgresSaver.from_conn_string(dsn))
            await saver.setup()
            _exit_stack = stack
            _checkpointer = saver
            logger.info("LangGraph AsyncPostgresSaver checkpointer ready")
            return
        except ImportError:
            await stack.aclose()
            logger.warning("langgraph-checkpoint-postgres not installed; using MemorySaver")
        except Exception as e:
            await stack.aclose()
            logger.warning("Postgres checkpointer init failed (%s); using MemorySaver", e)

    from langgraph.checkpoint.memory import MemorySaver

    _checkpointer = MemorySaver()
    logger.info("LangGraph MemorySaver checkpointer ready")


async def shutdown_checkpointer() -> None:
    global _checkpointer, _exit_stack
    if _exit_stack is not None:
        with suppress(Exception):
            await _exit_stack.aclose()
    _exit_stack = None
    _checkpointer = None


def compile_graph(graph: Any) -> Any:
    if _checkpointer is not None:
        return graph.compile(checkpointer=_checkpointer)
    return graph.compile()


def graph_astream(app: Any, init: Any, thread_id: str | None) -> AsyncIterator[Any]:
    if thread_id and checkpoint_active():
        return app.astream(
            init,
            config={"configurable": {"thread_id": str(thread_id)}},
        )
    return app.astream(init)
