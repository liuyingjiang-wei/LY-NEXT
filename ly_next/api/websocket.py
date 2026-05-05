"""WebSocket Manager."""

import asyncio
from datetime import datetime
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from ly_next.core.logger import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    def __init__(self):
        self._connections: list[WebSocket] = []
        self._groups: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, group: str | None = None) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.append(websocket)
        if group:
            await self.join_group(websocket, group)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)
            for g in self._groups.values():
                g.discard(websocket)

    async def send(self, websocket: WebSocket, message: dict[str, Any]) -> bool:
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_json(message)
                return True
        except Exception:
            pass
        return False

    async def broadcast(self, message: dict[str, Any], group: str | None = None) -> int:
        async with self._lock:
            targets = list(self._groups.get(group, set())) if group else list(self._connections)
        count = 0
        for ws in targets:
            if await self.send(ws, message):
                count += 1
        return count

    async def join_group(self, websocket: WebSocket, group: str) -> None:
        async with self._lock:
            self._groups.setdefault(group, set()).add(websocket)

    async def leave_group(self, websocket: WebSocket, group: str) -> None:
        async with self._lock:
            self._groups.get(group, set()).discard(websocket)


class TaskBroadcaster:
    def __init__(self, manager: ConnectionManager | None = None):
        self._manager = manager or get_ws_manager()

    async def _broadcast(self, event_type: str, data: dict[str, Any]) -> None:
        await self._manager.broadcast(
            {
                "type": event_type,
                "timestamp": datetime.now().isoformat(),
                **data,
            },
            group="tasks",
        )

    async def task_started(self, task_id: str, task_name: str):
        await self._broadcast("task_started", {"task_id": task_id, "task_name": task_name})

    async def task_progress(self, task_id: str, progress: float, message: str = ""):
        await self._broadcast(
            "task_progress", {"task_id": task_id, "progress": progress, "message": message}
        )

    async def task_completed(self, task_id: str, result: Any = None):
        await self._broadcast("task_completed", {"task_id": task_id, "result": result})

    async def task_failed(self, task_id: str, error: str):
        await self._broadcast("task_failed", {"task_id": task_id, "error": error})

    async def task_stopped(self, task_id: str):
        await self._broadcast("task_stopped", {"task_id": task_id})


_ws_manager: ConnectionManager | None = None
_task_broadcaster: TaskBroadcaster | None = None


def get_ws_manager() -> ConnectionManager:
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = ConnectionManager()
    return _ws_manager


def get_task_broadcaster() -> TaskBroadcaster:
    global _task_broadcaster
    if _task_broadcaster is None:
        _task_broadcaster = TaskBroadcaster()
    return _task_broadcaster
