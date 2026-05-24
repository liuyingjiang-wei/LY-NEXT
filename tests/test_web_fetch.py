from __future__ import annotations

import pytest

from ly_next.tools.web_fetch import WEB_FETCH_PROVIDERS, _dispatch, _settings, _truncate, web_fetch
from ly_next.tools.web_fetch_local import extract_html, looks_like_html


def test_truncate():
    text, truncated = _truncate("abcdef", 4)
    assert truncated
    assert text.startswith("abcd")


def test_looks_like_html():
    assert looks_like_html("<html><body>x</body></html>", "")
    assert not looks_like_html('{"a":1}', "application/json")


def test_trafilatura_extract_article():
    html = """
    <html><head><title>Demo</title></head><body>
    <nav>skip navigation</nav>
    <article><h1>Hello</h1><p>World content here with enough text for extraction.</p></article>
    </body></html>
    """
    text = extract_html(html, "https://example.com/article", output_format="txt")
    assert "Hello" in text
    assert "World content" in text
    assert len(text.strip()) > 20


@pytest.mark.asyncio
async def test_web_fetch_rejects_private_url():
    result = await web_fetch("http://127.0.0.1/")
    assert not result.success


@pytest.mark.asyncio
async def test_unknown_provider_dispatch():
    from ly_next.core.config import config

    old = config.get("tools.web_fetch")
    config.set("tools.web_fetch", {"provider": "not_a_vendor"})
    try:
        opts = _settings()
        opts["provider"] = "not_a_vendor"
        with pytest.raises(ValueError, match="Unknown web_fetch provider"):
            await _dispatch("https://example.com", opts)
    finally:
        config.set("tools.web_fetch", old)


def test_provider_list():
    assert "trafilatura" in WEB_FETCH_PROVIDERS
    assert "local" in WEB_FETCH_PROVIDERS
    assert "jina" in WEB_FETCH_PROVIDERS
