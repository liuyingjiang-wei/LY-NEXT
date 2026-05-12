import asyncio
import json

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
from starlette.websockets import WebSocketState

from ly_next import __version__
from ly_next.core.auth_http import extract_api_key_from_websocket
from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.mcp.server import MCPError, mcp_server

logger = get_logger(__name__)


def get_mcp_mount_prefix() -> str:
    p = config.get("tools.mcp.path", "/mcp") or "/mcp"
    p = str(p).strip()
    if not p.startswith("/"):
        p = "/" + p
    p = p.rstrip("/")
    return p if p else "/mcp"


mcp_router = APIRouter(tags=["mcp"])


async def _ws_auth_ok(websocket: WebSocket) -> bool:
    if not config.get("auth.enabled", True):
        return True
    key = config.get("auth.api_key", "")
    if not key:
        return True
    header_name = config.get("auth.header_name", "X-API-Key")
    cookie_name = config.get("auth.cookie_name", "ly_api_key")
    allow_query = bool(config.get("auth.allow_api_key_in_query", False))
    provided = extract_api_key_from_websocket(
        websocket,
        header_name=header_name,
        cookie_name=cookie_name,
        allow_query=allow_query,
    )
    if provided == key:
        return True
    if websocket.client_state != WebSocketState.CONNECTED:
        await websocket.accept()
    await websocket.send_json(
        {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "Unauthorized"}}
    )
    await websocket.close(code=1008)
    return False


@mcp_router.websocket("/ws")
async def mcp_ws(websocket: WebSocket):
    if not await _ws_auth_ok(websocket):
        return
    await websocket.accept()
    await websocket.send_json({"type": "connected", "protocol": "mcp-1.0"})
    try:
        while True:
            body = await websocket.receive_json()
            method = body.get("method")
            params = body.get("params", {})
            msg_id = body.get("id")
            if not method:
                await websocket.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {"code": -32600, "message": "Invalid Request"},
                    }
                )
                continue
            try:
                result = await mcp_server.handle_message(method, params)
                await websocket.send_json({"jsonrpc": "2.0", "id": msg_id, "result": result})
            except MCPError as e:
                await websocket.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {"code": e.code, "message": e.message},
                    }
                )
            except Exception as e:
                await websocket.send_json(
                    {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32603, "message": str(e)}}
                )
    except WebSocketDisconnect:
        return
    except Exception as e:
        logger.error(f"MCP WS error: {e}")


@mcp_router.get("")
async def mcp_sse():
    async def event_generator():
        yield {"event": "endpoint", "data": get_mcp_mount_prefix()}

        for method, items in [
            ("tools/list", {"tools": [t.to_dict() for t in mcp_server.tools]}),
            ("resources/list", {"resources": [r.to_dict() for r in mcp_server.resources]}),
            ("prompts/list", {"prompts": [p.to_dict() for p in mcp_server.prompts]}),
        ]:
            yield {
                "event": "message",
                "data": json.dumps({"method": method, "params": {}, "result": items}),
            }

        yield {
            "event": "message",
            "data": json.dumps(
                {
                    "method": "initialized",
                    "params": {},
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {"listChanged": True},
                            "resources": {"subscribe": True, "listChanged": True},
                            "prompts": {"listChanged": True},
                        },
                        "serverInfo": {"name": "ly-next", "version": __version__},
                    },
                }
            ),
        }

        while True:
            await asyncio.sleep(30)
            yield {"event": "ping", "data": ""}

    return EventSourceResponse(event_generator())


@mcp_router.post("")
async def mcp_message(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}, status_code=400
        )

    method = body.get("method")
    params = body.get("params", {})
    msg_id = body.get("id")

    if not method:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32600, "message": "Invalid Request"},
            },
            status_code=400,
        )

    try:
        result = await mcp_server.handle_message(method, params)
        return JSONResponse({"jsonrpc": "2.0", "id": msg_id, "result": result})
    except MCPError as e:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": msg_id, "error": {"code": e.code, "message": e.message}}
        )
    except Exception as e:
        logger.error(f"MCP error: {e}")
        return JSONResponse(
            {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32603, "message": str(e)}}
        )


@mcp_router.get("/tools")
async def list_tools():
    return {"tools": [t.to_dict() for t in mcp_server.tools], "count": len(mcp_server.tools)}


@mcp_router.get("/resources")
async def list_resources():
    return {
        "resources": [r.to_dict() for r in mcp_server.resources],
        "count": len(mcp_server.resources),
    }


@mcp_router.get("/prompts")
async def list_prompts():
    return {"prompts": [p.to_dict() for p in mcp_server.prompts], "count": len(mcp_server.prompts)}
