from unittest.mock import patch

import pytest

from ly_next.core.auth_gate import authenticate_http, authorize_http
from ly_next.core.auth_jwt import issue_access_token, verify_access_token
from ly_next.core.auth_principal import Principal, required_permission


def test_required_permission_admin_settings():
    assert required_permission("PATCH", "/api/system/settings") == "admin"
    assert required_permission("GET", "/api/tools/list_tools") == "viewer"
    assert required_permission("POST", "/api/chat") == "operator"


def test_principal_role_ordering():
    viewer = Principal("u", "viewer", "jwt")
    admin = Principal("a", "admin", "jwt")
    assert not viewer.has_role("operator")
    assert admin.has_role("operator")


@pytest.mark.asyncio
async def test_authenticate_http_accepts_api_key():
    class _Client:
        host = "127.0.0.1"

    class _Req:
        headers = {"X-API-Key": "test-key"}
        cookies = {}
        query_params = {}

        client = _Client()

    with (
        patch(
            "ly_next.core.auth_gate.config.get",
            side_effect=lambda k, d=None: {
                "auth.mode": "api_key",
                "auth.api_key": "test-key",
                "auth.header_name": "X-API-Key",
                "auth.cookie_name": "ly_api_key",
                "auth.allow_api_key_in_query": False,
            }.get(k, d),
        ),
        patch("ly_next.core.auth_gate.jwt_enabled", return_value=False),
    ):
        principal = authenticate_http(_Req())
    assert principal is not None
    assert principal.role == "service"


def test_jwt_issue_and_verify():
    with (
        patch(
            "ly_next.core.auth_jwt.jwt_config",
            return_value={"secret": "unit-test-secret-with-32-byte-minimum-length"},
        ),
        patch("ly_next.core.auth_jwt.config.get", return_value="api_key"),
    ):
        token, ttl = issue_access_token(username="alice", role="operator")
        assert ttl > 0
        payload = verify_access_token(token)
        assert payload is not None
        assert payload["sub"] == "alice"
        assert payload["role"] == "operator"


def test_rbac_blocks_viewer_on_chat_post():
    principal = Principal("bob", "viewer", "jwt")

    class _Req:
        method = "POST"
        url = type("U", (), {"path": "/api/chat"})()

    with patch("ly_next.core.auth_gate.rbac_enabled", return_value=True):
        allowed, reason = authorize_http(principal, _Req())
    assert allowed is False
    assert "operator" in (reason or "")
