from fastapi.testclient import TestClient

from ly_next.core.config import config
from ly_next.main import create_app


def _api_headers() -> dict[str, str]:
    key = str(config.get("auth.api_key", "") or "")
    name = str(config.get("auth.header_name", "X-API-Key") or "X-API-Key")
    return {name: key}


def test_system_extensions_includes_plugins():
    with TestClient(create_app()) as client:
        r = client.get("/api/system/extensions", headers=_api_headers())
    assert r.status_code == 200
    data = r.json()

    assert "plugins" in data
    assert isinstance(data["plugins"], list)
    assert data["plugins_summary"]["total"] == len(data["plugins"])
    assert data["plugins_summary"]["builtin"] >= 3
    assert "plugins_config" in data
    assert "dir" in data["plugins_config"]
    assert "tool_count" in data
    assert isinstance(data.get("agent_modes"), list)
    assert "host_platform" in data
    assert isinstance(data["host_platform"].get("platform"), str)
    assert "skills" in data
    assert isinstance(data["skills"], dict)
    assert "host_approvals_pending" in data
    assert isinstance(data["host_approvals_pending"], int)

    names = {p["name"] for p in data["plugins"]}
    assert "ly-next-builtin" in names
    for p in data["plugins"]:
        assert "name" in p
        assert "builtin" in p
        assert isinstance(p["builtin"], bool)
