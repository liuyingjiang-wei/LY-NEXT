"""Sample API."""

import asyncio
from datetime import datetime

from fastapi import FastAPI
from pydantic import BaseModel

from ly_next.api.base import BaseAPI


class EchoRequest(BaseModel):
    message: str
    delay: float = 0


class SampleAPI(BaseAPI):
    """Sample API."""

    def __init__(self):
        super().__init__(
            name="sample-api",
            description="Sample API with echo and info endpoints",
            priority=50,
            enabled=True,
        )

    def register_routes(self, app: FastAPI) -> None:
        self.routes = [
            {"path": "/api/sample/info", "method": "GET", "description": "Get API info"},
            {"path": "/api/sample/echo", "method": "POST", "description": "Echo message"},
            {"path": "/api/sample/time", "method": "GET", "description": "Get server time"},
        ]

        @app.get("/api/sample/info")
        async def get_info():
            return {
                "name": self.name,
                "description": self.description,
                "version": "1.0.0",
                "endpoints": self.routes,
            }

        @app.post("/api/sample/echo")
        async def echo(request: EchoRequest):
            if request.delay > 0:
                await asyncio.sleep(request.delay)
            return {"echo": request.message, "delay": request.delay}

        @app.get("/api/sample/time")
        async def get_time():
            return {"iso": datetime.now().isoformat(), "timestamp": datetime.now().timestamp()}


default = SampleAPI()
