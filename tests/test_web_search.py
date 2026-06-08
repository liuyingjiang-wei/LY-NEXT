from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ly_next.tools.web_search import run_web_search, web_search
from ly_next.tools.web_shared import normalize_search_hit


def test_normalize_search_hit_shape():
    hit = normalize_search_hit(title="T", url="https://x.test", snippet="S")
    assert hit == {"title": "T", "url": "https://x.test", "snippet": "S"}


@pytest.mark.asyncio
async def test_run_web_search_returns_normalized_results():
    fake = [
        normalize_search_hit(title="A", url="https://a.test", snippet="sa"),
    ]
    with patch(
        "ly_next.tools.web_search._resolve_provider",
        return_value=("duckduckgo", ""),
    ), patch(
        "ly_next.tools.web_search._search_duckduckgo",
        new_callable=AsyncMock,
        return_value=fake,
    ):
        provider, results = await run_web_search("openclaw tools", count=3)

    assert provider == "duckduckgo"
    assert results[0]["url"] == "https://a.test"
    assert "href" not in results[0]
    assert "body" not in results[0]


@pytest.mark.asyncio
async def test_web_search_accepts_count_alias():
    fake = [normalize_search_hit(title="A", url="https://a.test", snippet="sa")]
    with patch(
        "ly_next.tools.web_search.run_web_search",
        new_callable=AsyncMock,
        return_value=("duckduckgo", fake),
    ) as run:
        result = await web_search("test", count=2)

    run.assert_awaited_once_with("test", 2)
    assert result.success is True
    assert result.result["count"] == 1
