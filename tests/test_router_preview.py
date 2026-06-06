from fastapi.testclient import TestClient

from ly_next.core.config import config
from ly_next.main import create_app


def _api_headers() -> dict[str, str]:
    key = str(config.get("auth.api_key", "") or "")
    name = str(config.get("auth.header_name", "X-API-Key") or "X-API-Key")
    return {name: key}


def test_router_preview_rejects_empty_text():
    client = TestClient(create_app())
    r = client.post(
        "/api/system/router/preview",
        headers=_api_headers(),
        json={"text": "   "},
    )
    assert r.status_code == 400


def test_router_preview_returns_routing_payload():
    client = TestClient(create_app())
    r = client.post(
        "/api/system/router/preview",
        headers=_api_headers(),
        json={"text": "帮我写一段 Python 快速排序"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "router_enabled" in data
    assert "router" in data
    router = data["router"]
    assert "task_kind" in router
    assert "via" in router
