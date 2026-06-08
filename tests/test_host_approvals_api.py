from fastapi.testclient import TestClient

from ly_next.core.config import config
from ly_next.main import create_app
from ly_next.tools import host_approvals as ha


def _api_headers() -> dict[str, str]:
    key = str(config.get("auth.api_key", "") or "")
    name = str(config.get("auth.header_name", "X-API-Key") or "X-API-Key")
    return {name: key}


def test_host_approvals_api_flow():
    ha._store.clear()
    item = ha.create_approval(
        tool="host_delete_path",
        action="delete",
        summary="Delete test",
        payload={"path": "/tmp/x"},
    )

    with TestClient(create_app()) as client:
        headers = _api_headers()
        r = client.get("/api/system/host-approvals?status=pending", headers=headers)
        assert r.status_code == 200
        pending = r.json()["approvals"]
        assert any(a["id"] == item.id for a in pending)

        r2 = client.post(f"/api/system/host-approvals/{item.id}/approve", headers=headers)
        assert r2.status_code == 200
        assert r2.json()["approval"]["status"] == "approved"

        r3 = client.post(f"/api/system/host-approvals/{item.id}/approve", headers=headers)
        assert r3.status_code == 409

    ha._store.clear()


def test_host_approvals_invalid_status():
    with TestClient(create_app()) as client:
        r = client.get("/api/system/host-approvals?status=bad", headers=_api_headers())
    assert r.status_code == 400
