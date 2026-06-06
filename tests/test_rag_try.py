from fastapi.testclient import TestClient

from ly_next.core.config import config
from ly_next.main import create_app


def _api_headers() -> dict[str, str]:
    key = str(config.get("auth.api_key", "") or "")
    name = str(config.get("auth.header_name", "X-API-Key") or "X-API-Key")
    return {name: key}


def test_rag_try_rejects_empty_query():
    client = TestClient(create_app())
    r = client.post(
        "/api/system/rag/try",
        headers=_api_headers(),
        json={"query": ""},
    )
    assert r.status_code == 400


def test_rag_try_returns_structured_result():
    client = TestClient(create_app())
    r = client.post(
        "/api/system/rag/try",
        headers=_api_headers(),
        json={"query": "PostgreSQL 配置"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "enabled" in data
    assert "hits" in data
    assert isinstance(data["hits"], list)
