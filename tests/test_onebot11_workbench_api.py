"""OneBot HTTP 代理 API。"""

from fastapi.testclient import TestClient

from ly_next.bridge.onebot11.napcat_actions import NAPCAT_ACTION_NAMES
from ly_next.core.config import config
from ly_next.main import create_app


def _api_headers() -> dict[str, str]:
    key = str(config.get("auth.api_key", "") or "")
    name = str(config.get("auth.header_name", "X-API-Key") or "X-API-Key")
    return {name: key}


def test_onebot11_status_endpoint():
    client = TestClient(create_app())
    r = client.get("/api/onebot11/status", headers=_api_headers())
    assert r.status_code == 200
    data = r.json()
    assert data["napcat_ws_url"].startswith("ws://")
    assert data["actions_count"] == len(NAPCAT_ACTION_NAMES)


def test_settings_includes_bridge_editable():
    client = TestClient(create_app())
    r = client.get("/api/system/settings", headers=_api_headers())
    assert r.status_code == 200
    editable = r.json().get("editable") or {}
    assert "bridge" in editable
    ob = editable["bridge"].get("onebot11") or {}
    assert ob.get("enabled") is not False


def test_onebot11_actions_list():
    client = TestClient(create_app())
    r = client.get("/api/onebot11/actions", headers=_api_headers())
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == len(NAPCAT_ACTION_NAMES)
    assert "send_private_msg" in data["actions"]
    assert ".ocr_image" in data["invoke_only"]


def test_onebot11_call_requires_connection():
    client = TestClient(create_app())
    r = client.post(
        "/api/onebot11/call",
        headers=_api_headers(),
        json={"action": "get_login_info", "params": {}},
    )
    assert r.status_code == 503


def test_onebot11_call_invalid_action():
    client = TestClient(create_app())
    r = client.post(
        "/api/onebot11/call",
        headers=_api_headers(),
        json={"action": "not valid!", "params": {}},
    )
    assert r.status_code == 400
