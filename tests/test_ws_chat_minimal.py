from __future__ import annotations

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
async def test_handle_chat_empty_messages():
    ws = MagicMock()
    ws.send_json = AsyncMock()
    await ws_api.handle_chat(ws, {"type": "chat", "messages": []})
    ws.send_json.assert_awaited_once()
    assert ws.send_json.call_args[0][0]["type"] == "error"
