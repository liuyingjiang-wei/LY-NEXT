"""OneBot WebSocket 路由必须挂在 app 上（include_router 之前 attach）。"""

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
    app = create_app()
    paths = _app_onebot_ws_paths(app)
    assert "/onebot/v11/ws" in paths
    assert "/OneBotv11" in paths
