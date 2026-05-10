from fastapi import APIRouter

from ly_next.api.mcp_api import mcp_router
from ly_next.api.wei_api import router as wei_router
from ly_next.api.ws_api import public_router as ws_public_router
from ly_next.api.ws_api import router as ws_router

api_router = APIRouter(prefix="/api")
api_router.include_router(wei_router)
api_router.include_router(ws_router)

__all__ = ["api_router", "mcp_router", "ws_public_router"]
