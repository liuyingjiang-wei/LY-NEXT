from fastapi.testclient import TestClient

from ly_next.core.config import config
from ly_next.main import create_app


def _api_headers() -> dict[str, str]:
    key = str(config.get("auth.api_key", "") or "")
    name = str(config.get("auth.header_name", "X-API-Key") or "X-API-Key")
    return {name: key}


def test_security_health_endpoint():
    client = TestClient(create_app())
    r = client.get("/api/system/security/health", headers=_api_headers())
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data.get("checks"), list)
    assert "all_ok" in data
