from unittest.mock import patch

from fastapi.testclient import TestClient

from ly_next.main import create_app


def test_auth_config_endpoint():
    client = TestClient(create_app())
    r = client.get("/api/auth/config")
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] in ("api_key", "jwt", "hybrid")
    assert "rbac_enabled" in data


def test_auth_login_with_users(monkeypatch):
    "pbkdf2_sha256$" + "00" * 16 + "$" + "11" * 32
    with (
        patch("ly_next.api.auth_api.users_configured", return_value=True),
        patch("ly_next.api.auth_api.jwt_enabled", return_value=True),
        patch(
            "ly_next.api.auth_api.login_with_password",
            return_value=type(
                "P",
                (),
                {"subject": "admin", "role": "admin", "auth_method": "jwt"},
            )(),
        ),
        patch(
            "ly_next.api.auth_api.issue_access_token",
            return_value=("token-abc", 3600),
        ),
    ):
        client = TestClient(create_app())
        r = client.post("/api/auth/login", json={"username": "admin", "password": "x"})
    assert r.status_code == 200
    assert r.json()["access_token"] == "token-abc"
