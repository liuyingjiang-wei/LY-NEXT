import inspect
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from ly_next.core.logger import get_logger

logger = get_logger(__name__)


class BaseAPI:
    def __init__(
        self,
        name: str,
        description: str = "",
        priority: int = 100,
        enabled: bool = True,
    ):
        self.name = name
        self.description = description or "No description"
        self.priority = priority
        self.enabled = enabled
        self.routes: list[dict[str, Any]] = []
        self._registered = False

    def register_routes(self, app: FastAPI) -> None:
        logger.warning(f"[BaseAPI] {self.name} does not implement register_routes")

    async def init(self, app: FastAPI) -> None:
        pass

    async def startup(self, app: FastAPI) -> None:
        if not self.enabled:
            logger.info(f"[BaseAPI] {self.name} is disabled, skipping registration")
            return

        try:
            self.register_routes(app)
            await self.init(app)
            self._registered = True
            logger.info(f"[BaseAPI] {self.name} registered ({len(self.routes)} routes)")
        except Exception as e:
            logger.error(f"[BaseAPI] {self.name} registration failed: {e}", exc_info=True)
            raise

    async def shutdown(self, app: FastAPI) -> None:
        pass

    def get_info(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "priority": self.priority,
            "enabled": self.enabled,
            "routes_count": len(self.routes),
            "registered": self._registered,
        }


def create_api_from_dict(data: dict[str, Any]) -> BaseAPI:
    class DictAPI(BaseAPI):
        def __init__(self, data: dict[str, Any]):
            super().__init__(
                name=data.get("name", "unnamed-api"),
                description=data.get("description", ""),
                priority=data.get("priority", 100),
                enabled=data.get("enabled", True),
            )
            self._data = data

        def register_routes(self, app: FastAPI) -> None:
            routes = self._data.get("routes", [])
            route_methods = {
                "GET": app.get,
                "POST": app.post,
                "PUT": app.put,
                "DELETE": app.delete,
                "PATCH": app.patch,
            }

            for route_config in routes:
                method = route_config.get("method", "GET").upper()
                path = route_config.get("path")
                handler = route_config.get("handler")

                if not path or not handler:
                    continue

                if method not in route_methods:
                    continue

                wrapped_handler = self._wrap_handler(handler)
                route_methods[method](path)(wrapped_handler)
                self.routes.append(route_config)

        async def init(self, app: FastAPI) -> None:
            init_hook = self._data.get("init")
            if not (init_hook and callable(init_hook)):
                return

            if inspect.iscoroutinefunction(init_hook):
                await init_hook(app)
            else:
                result = init_hook(app)
                if inspect.isawaitable(result):
                    await result

        def _wrap_handler(self, handler: Callable) -> Callable:
            is_async = inspect.iscoroutinefunction(handler)

            async def wrapped(request: Request):
                try:
                    return await handler(request) if is_async else handler(request)
                except HTTPException:
                    raise
                except Exception as e:
                    logger.error(
                        f"[DictAPI] {self.name} request handling failed: {e}", exc_info=True
                    )
                    raise HTTPException(status_code=500, detail=str(e)) from e

            return wrapped

    return DictAPI(data)


class APIRegistry:
    def __init__(self):
        self._apis: list[BaseAPI] = []
        self._by_name: dict[str, BaseAPI] = {}

    def register(self, api: BaseAPI | dict[str, Any]) -> None:
        if isinstance(api, dict):
            api = create_api_from_dict(api)

        if api.name in self._by_name:
            logger.warning(f"[APIRegistry] Overwriting existing API: {api.name}")
            old = self._by_name.get(api.name)
            if old is not None:
                self._apis = [a for a in self._apis if a is not old]

        self._apis.append(api)
        self._by_name[api.name] = api
        self._apis.sort(key=lambda x: x.priority, reverse=True)

    def get(self, name: str) -> BaseAPI | None:
        return self._by_name.get(name)

    def list_apis(self) -> list[BaseAPI]:
        return list(self._apis)

    def list_info(self) -> list[dict[str, Any]]:
        return [api.get_info() for api in self._apis]

    async def startup(self, app: FastAPI) -> None:
        for api in self._apis:
            if api.enabled:
                await api.startup(app)

    async def shutdown(self, app: FastAPI) -> None:
        for api in self._apis:
            if api._registered:
                await api.shutdown(app)
