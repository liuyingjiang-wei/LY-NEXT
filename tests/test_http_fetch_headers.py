from __future__ import annotations

from ly_next.tools.http_fetch import _normalize_headers


def test_normalize_drops_host_and_forwarded():
    h = _normalize_headers(
        {
            "Host": "evil.internal",
            "X-Forwarded-For": "127.0.0.1",
            "Authorization": "Bearer x",
            "Accept": "application/json",
        }
    )
    assert "Host" not in {k.lower() for k in h}
    assert "authorization" in {k.lower() for k in h}
    assert h.get("Accept") == "application/json"
