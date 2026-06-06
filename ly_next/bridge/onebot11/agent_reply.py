from __future__ import annotations

from ly_next.agent.chat_pipeline import (
    ChatTurnRequest,
    await_user_persist,
    build_agent_deps,
    prepare_chat_turn,
    run_agent_on_prepared,
)
from ly_next.agent.image_reply import ensure_mixed_reply
from ly_next.bridge.onebot11.config import OneBot11AutoReply
from ly_next.bridge.onebot11.memory import onebot_history_limit, onebot_include_global_memory
from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.core.run_lifecycle import finish_observed_run, start_observed_run
from ly_next.core.task_manager import get_task_manager
from ly_next.core.thread_persistence import persist_chat_turn
from ly_next.messaging.models import MixedMessage, mixed_message_to_dict

logger = get_logger(__name__)


class OneBotChatResult:
    __slots__ = ("text", "mixed")

    def __init__(self, text: str, mixed: MixedMessage) -> None:
        self.text = text
        self.mixed = mixed


def _onebot_augment_flags() -> tuple[bool, bool, bool, bool]:
    """(skip_augment, skip_rag, skip_context, skip_memory)"""
    ob = config.get("bridge.onebot11", {}) or {}
    auto = ob.get("auto_reply", {}) or {} if isinstance(ob, dict) else {}
    if not isinstance(auto, dict):
        auto = {}
    if auto.get("skip_augment") is True:
        return True, True, True, True
    skip_rag = bool(auto.get("skip_rag", True))
    skip_ctx = bool(auto.get("skip_context", True))
    skip_mem = not onebot_include_global_memory()
    skip_all = skip_rag and skip_ctx and skip_mem
    return skip_all, skip_rag, skip_ctx, skip_mem


async def run_onebot_chat_turn(
    *,
    user_text: str,
    thread_id: str,
    scope_key: str,
    auto: OneBot11AutoReply,
) -> OneBotChatResult:
    manager = get_task_manager()
    task_id = await manager.create_task(name="OneBot11 Chat")
    await manager.update(task_id, status="running")

    client_messages = [{"role": "user", "content": user_text}]
    telemetry_token = None
    run_status = "ok"
    run_error: str | None = None
    result_text = ""
    mixed = MixedMessage(parts=[])

    prepared = None
    try:
        skip_all, skip_rag, skip_ctx, skip_mem = _onebot_augment_flags()
        prepared = await prepare_chat_turn(
            ChatTurnRequest(
                client_messages=client_messages,
                thread_id=thread_id,
                mode=auto.mode,
                temperature=auto.temperature,
                max_tokens=auto.max_tokens,
                provider=auto.provider,
                model=auto.model,
                skip_vision_precaption=True,
                skip_augment=skip_all,
                skip_rag=skip_rag,
                skip_context=skip_ctx,
                skip_memory=skip_mem,
                history_limit=onebot_history_limit(),
                turn_meta_extra={
                    "task_id": task_id,
                    "channel": "OneBot11",
                    "onebot_scope": scope_key,
                },
            )
        )
        telemetry_token = await start_observed_run(
            task_id,
            mode=auto.mode,
            thread_id=prepared.thread_id,
            router=prepared.router_payload,
        )
        deps = build_agent_deps(
            prepared,
            temperature=auto.temperature,
            max_tokens=auto.max_tokens,
        )
        result_text = await run_agent_on_prepared(prepared, deps, mode=auto.mode)
        mixed = await ensure_mixed_reply(deps, result_text)

        assist_meta = {
            **prepared.turn_meta,
            "task_id": task_id,
            "run_id": task_id,
            "mixed_message": mixed_message_to_dict(mixed),
            "image_urls": mixed.image_urls(),
        }
        await persist_chat_turn(
            prepared.thread_id,
            [],
            result_text,
            metadata=assist_meta,
        )
        await manager.complete(task_id, result=result_text)
    except Exception as e:
        run_status = "error"
        run_error = str(e)
        await manager.fail(task_id, str(e))
        logger.exception("[onebot11] agent turn failed task=%s: %s", task_id, e)
        raise
    finally:
        if prepared is not None:
            await await_user_persist(prepared)
        if telemetry_token is not None:
            snap = await finish_observed_run(
                telemetry_token, task_id, status=run_status, error=run_error
            )
            if snap:
                logger.info("[onebot11] task=%s run_summary=%s", task_id, snap)

    return OneBotChatResult(result_text, mixed)


def build_thread_id(message_type: str, *, user_id: int, group_id: int | None = None) -> str:
    if message_type == "group" and group_id is not None:
        return f"onebot:group:{group_id}"
    return f"onebot:private:{user_id}"
