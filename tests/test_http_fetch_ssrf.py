from unittest.mock import patch

import pytest

from ly_next.tools.http_fetch import _url_allowed


def test_url_allowed_blocks_resolved_private_ip():
    with patch(
        "ly_next.tools.http_fetch.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("127.0.0.1", 0))],
    ):
        ok, err = _url_allowed("http://rebind.example/")
    assert ok is False
    assert err is not None
    assert "127.0.0.1" in err or "resolved" in err


def test_url_allowed_blocks_resolved_metadata_ip():
    with patch(
        "ly_next.tools.http_fetch.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("169.254.169.254", 0))],
    ):
        ok, err = _url_allowed("https://metadata-host.example/latest")
    assert ok is False
    assert err is not None


@pytest.mark.asyncio
async def test_http_fetch_blocks_dns_rebinding_before_request():
    from ly_next.tools.http_fetch import http_fetch

    with patch(
        "ly_next.tools.http_fetch.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("127.0.0.1", 0))],
    ):
        result = await http_fetch.execute(url="http://evil.example/")
    assert result.success is False
    assert result.error
