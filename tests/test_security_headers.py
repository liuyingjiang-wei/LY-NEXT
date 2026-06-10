from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ly_next.core.security_headers import SecurityHeadersMiddleware


def test_security_headers_middleware_adds_defaults():
    app = FastAPI()

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    with patch(
        "ly_next.core.security_headers.headers_config",
        return_value={
            "enabled": True,
            "hsts": False,
            "frame_options": "DENY",
            "content_type_options": True,
            "referrer_policy": "strict-origin-when-cross-origin",
            "content_security_policy": "default",
        },
    ):
        app.add_middleware(SecurityHeadersMiddleware)
        client = TestClient(app)
        r = client.get("/ping")
        assert r.status_code == 200
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "DENY"
        assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert "Content-Security-Policy" in r.headers
