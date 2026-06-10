import pytest
from fastapi.testclient import TestClient

pytest.importorskip("telegram_bot")

from ly_next.core.config import config
from ly_next.main import create_app


def _api_headers() -> dict[str, str]:
    key = str(config.get("auth.api_key", "") or "")
    name = str(config.get("auth.header_name", "X-API-Key") or "X-API-Key")
    return {name: key}


def test_telegram_status_endpoint():
    with TestClient(create_app()) as client:
        r = client.get("/api/telegram/status", headers=_api_headers())
    assert r.status_code == 200
    data = r.json()
    assert data.get("dm_policy") in ("pairing", "allowlist", "open", "disabled")
    assert "allowlist_count" in data
    assert "pending_count" in data
    assert "approved_count" in data


def test_telegram_allowlist_parse_endpoint():
    with TestClient(create_app()) as client:
        r = client.post(
            "/api/telegram/allowlist/parse",
            headers=_api_headers(),
            json={"text": "6537629878\n@baduser"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["user_ids"] == [6537629878]
    assert len(data["rejected"]) == 1


def test_telegram_pairing_endpoints():
    with TestClient(create_app()) as client:
        h = _api_headers()
        assert client.get("/api/telegram/pairing/pending", headers=h).status_code == 200
        assert client.get("/api/telegram/pairing/approved", headers=h).status_code == 200
        r = client.post("/api/telegram/pairing/approve", headers=h, json={"code": "PAIR-XXXX"})
        assert r.status_code == 404


def test_telegram_plugin_loaded():
    pytest.importorskip("qq_onebot")
    with TestClient(create_app()) as client:
        r = client.get("/api/system/extensions", headers=_api_headers())
    assert r.status_code == 200
    names = {p["name"] for p in r.json().get("plugins") or []}
    assert "telegram-bot" in names
    assert "qq-onebot" in names
