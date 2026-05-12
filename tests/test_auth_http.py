from __future__ import annotations

from starlette.requests import Request

from ly_next.core.auth_http import extract_api_key_from_request


def _request(query: bytes = b"", headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "method": "GET",
            "path": "/",
            "raw_path": b"/",
            "headers": headers or [],
            "query_string": query,
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
    )


def test_extract_from_header():
    r = _request(headers=[(b"x-api-key", b"secret")])
    v = extract_api_key_from_request(
        r, header_name="X-API-Key", cookie_name="ly_api_key", allow_query=True
    )
    assert v == "secret"


def test_query_ignored_when_disabled():
    r = _request(query=b"api_key=leak")
    v = extract_api_key_from_request(
        r, header_name="X-API-Key", cookie_name="ly_api_key", allow_query=False
    )
    assert v is None


def test_query_used_when_enabled():
    r = _request(query=b"api_key=abc")
    v = extract_api_key_from_request(
        r, header_name="X-API-Key", cookie_name="ly_api_key", allow_query=True
    )
    assert v == "abc"
