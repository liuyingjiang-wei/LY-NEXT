from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ly_next.api import ws_api


@pytest.fixture
def ws_app():
    app = FastAPI()
    app.include_router(ws_api.router, prefix="/api")
    return app


def test_ws_unknown_message_returns_error(ws_app, monkeypatch):
    monkeypatch.setattr(ws_api, "_ws_auth_ok", AsyncMock(return_value=True))
    client = TestClient(ws_app)
    with client.websocket_connect("/api/ws") as socket:
        socket.send_json({"type": "not_a_real_type"})
        msg = socket.receive_json()
    assert msg.get("type") == "error"
    assert "Unknown" in (msg.get("message") or "")


@pytest.mark.asyncio
async def test_listen_cancel_ws_swallows_task_cancel():
    ws = MagicMock()
    ws.receive_json = AsyncMock(side_effect=asyncio.CancelledError())
    manager = MagicMock()
    manager.stop = AsyncMock()
    pump_holder: dict = {"task": None}

    await ws_api._listen_cancel_ws(ws, "task-1", manager, pump_holder)

    manager.stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_task_gather_does_not_raise():
    """与 handle_chat finally 相同：gather(return_exceptions=True) 吞掉 CancelledError。"""

    async def fake_listen():
        await asyncio.sleep(3600)

    cancel_task = asyncio.create_task(fake_listen())
    await asyncio.sleep(0)
    cancel_task.cancel()
    results = await asyncio.gather(cancel_task, return_exceptions=True)
    assert len(results) == 1
    assert isinstance(results[0], asyncio.CancelledError)


@pytest.mark.asyncio
async def test_handle_chat_recv_does_not_crash_before_prepare(monkeypatch):
    """Regression: requested_mode/thread_id must exist before chat_trace recv log."""
    sent: list[dict] = []

    async def capture_send(payload):
        sent.append(payload)

    ws = MagicMock()
    ws.send_json = AsyncMock(side_effect=capture_send)

    monkeypatch.setattr(
        ws_api,
        "begin_chat_task",
        AsyncMock(return_value=type("H", (), {"task_id": "task-test-1", "name": "WebSocket Chat"})()),
    )
    monkeypatch.setattr(ws_api, "get_task_manager", lambda: MagicMock(
        update=AsyncMock(),
        get_stop_event=MagicMock(return_value=None),
        is_stopped=MagicMock(return_value=False),
        complete=AsyncMock(),
        fail=AsyncMock(),
    ))
    monkeypatch.setattr(
        ws_api,
        "get_task_broadcaster",
        lambda: MagicMock(task_started=AsyncMock(), task_completed=AsyncMock()),
    )
    monkeypatch.setattr(ws_api, "prepare_turn", AsyncMock(side_effect=ValueError("stop early")))
    monkeypatch.setattr(ws_api, "chat_trace_info", MagicMock())
    monkeypatch.setattr(ws_api, "chat_trace_warn", MagicMock())

    await ws_api.handle_chat(
        ws,
        {
            "type": "chat",
            "mode": "chat",
            "thread_id": "b683749a-e4d8-4ed8-9a8d-fe93abbc6afa",
            "messages": [{"role": "user", "content": "你好"}],
        },
    )

    assert any(m.get("type") == "chat_ack" for m in sent)
    ws_api.chat_trace_info.assert_called()
    first_call = ws_api.chat_trace_info.call_args_list[0]
    assert first_call[0][0] == "recv"
    assert first_call[1]["requested_mode"] == "chat"


@pytest.mark.asyncio
async def test_handle_chat_sends_chat_started_after_routed_log(monkeypatch):
    """Regression: routed log must not reference removed task_kind on ChatModelSelection."""
    from ly_next.agent.chat_model import ChatModelSelection, selection_payload
    from ly_next.agent.chat_pipeline import PreparedChatTurn

    sent: list[dict] = []

    async def capture_send(payload):
        sent.append(payload)

    ws = MagicMock()
    ws.send_json = AsyncMock(side_effect=capture_send)

    manager = MagicMock(
        update=AsyncMock(),
        get_stop_event=MagicMock(return_value=None),
        is_stopped=MagicMock(return_value=False),
        complete=AsyncMock(),
        fail=AsyncMock(),
    )
    monkeypatch.setattr(
        ws_api,
        "begin_chat_task",
        AsyncMock(return_value=type("H", (), {"task_id": "task-routed-1", "name": "WebSocket Chat"})()),
    )
    routed = ChatModelSelection(
        name="openai",
        format="openai",
        model="gpt-4o-mini",
        via="default",
    )
    prepared = PreparedChatTurn(
        thread_id="thread-1",
        messages=[{"role": "user", "content": "hi"}],
        user_to_persist=[],
        routed=routed,
        turn_meta={"requested_mode": "chat"},
        router_payload=selection_payload(routed),
        plan=None,
    )


    monkeypatch.setattr(ws_api, "get_task_manager", lambda: manager)
    monkeypatch.setattr(
        ws_api,
        "get_task_broadcaster",
        lambda: MagicMock(
            task_started=AsyncMock(),
            task_completed=AsyncMock(),
            task_failed=AsyncMock(),
            task_stopped=AsyncMock(),
        ),
    )
    monkeypatch.setattr(ws_api, "prepare_turn", AsyncMock(return_value=(prepared, "chat")))
    monkeypatch.setattr(ws_api, "start_observed_run", AsyncMock(return_value=object()))
    monkeypatch.setattr(ws_api, "finish_observed_run", AsyncMock(return_value=None))
    monkeypatch.setattr(ws_api, "bind_agent_deps", MagicMock(return_value=MagicMock(tool_registry=None)))
    monkeypatch.setattr(ws_api, "run_turn_blocking", AsyncMock(return_value="ok"))
    monkeypatch.setattr(ws_api, "await_user_persist", AsyncMock())
    monkeypatch.setattr(
        ws_api,
        "ensure_mixed_reply",
        AsyncMock(return_value=MagicMock(image_urls=MagicMock(return_value=[]))),
    )
    monkeypatch.setattr(ws_api, "persist_chat_turn", AsyncMock())
    monkeypatch.setattr(ws_api, "chat_trace_info", MagicMock())
    monkeypatch.setattr(ws_api, "chat_trace_warn", MagicMock())
    monkeypatch.setattr(ws_api, "chat_trace_error", MagicMock())
    ws.receive_json = AsyncMock(side_effect=asyncio.CancelledError())

    await ws_api.handle_chat(
        ws,
        {
            "type": "chat",
            "mode": "chat",
            "stream": False,
            "messages": [{"role": "user", "content": "你好"}],
        },
    )

    assert any(m.get("type") == "chat_ack" for m in sent)
    assert any(m.get("type") == "chat_started" for m in sent)
    manager.fail.assert_not_awaited()
