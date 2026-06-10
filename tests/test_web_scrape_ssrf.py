import pytest

from ly_next.tools.web_search import web_scrape


@pytest.mark.asyncio
async def test_web_scrape_blocks_loopback():
    result = await web_scrape("http://127.0.0.1/")
    assert result.success is False
    assert result.error


@pytest.mark.asyncio
async def test_web_scrape_blocks_metadata_ip():
    result = await web_scrape("http://169.254.169.254/latest/meta-data/")
    assert result.success is False
    assert result.error


@pytest.mark.asyncio
async def test_web_scrape_blocks_non_http_scheme():
    result = await web_scrape("file:///etc/passwd")
    assert result.success is False
    assert "http" in (result.error or "").lower()
