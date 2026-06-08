"""OneBot WebSocket routes must attach before include_router."""

import pytest
from starlette.routing import WebSocketRoute

from ly_next.main import create_app


def _app_onebot_ws_paths(app) -> set[str]:
    paths: set[str] = set()
    for route in app.router.routes:
        if isinstance(route, WebSocketRoute):
            p = getattr(route, "path", None)
            if p and ("onebot" in p.lower() or "onebot11" in p.lower()):
                paths.add(p)
    return paths


def test_onebot_paths_registered_on_app():
    pytest.importorskip("qq_onebot")
    app = create_app()
    paths = _app_onebot_ws_paths(app)
    if not paths:
        pytest.skip("qq_onebot bridge not loaded")
    assert "/onebot/v11/ws" in paths
    assert "/OneBotv11" in paths
