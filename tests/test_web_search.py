from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ly_next.core.tool_result_spill import coerce_tool_payload_text
from ly_next.tools.web_search import run_web_search, web_search
from ly_next.tools.web_shared import (
    domain_matches,
    filter_results_by_domains,
    format_web_search_text,
    normalize_search_hit,
    suggest_fetch_urls,
)


def test_normalize_search_hit_shape():
    hit = normalize_search_hit(title="T", url="https://x.test", snippet="S")
    assert hit["title"] == "T"
    assert hit["url"] == "https://x.test"
    assert hit["snippet"] == "S"
    assert hit["domain"] == "x.test"
    assert "href" not in hit
    assert "body" not in hit


def test_domain_matches_subdomain():
    assert domain_matches("docs.github.com", "github.com")
    assert not domain_matches("evil-github.com", "github.com")


def test_filter_results_by_domains():
    rows = [
        normalize_search_hit(title="A", url="https://arxiv.org/abs/1", snippet=""),
        normalize_search_hit(title="B", url="https://example.com/x", snippet=""),
    ]
    kept = filter_results_by_domains(rows, allowed_domains=["arxiv.org"])
    assert len(kept) == 1
    assert kept[0]["domain"] == "arxiv.org"


def test_suggest_fetch_urls_dedupes():
    rows = [
        normalize_search_hit(title="A", url="https://a.test", snippet=""),
        normalize_search_hit(title="B", url="https://a.test", snippet=""),
        normalize_search_hit(title="C", url="https://b.test", snippet=""),
    ]
    assert suggest_fetch_urls(rows, max_urls=3) == ["https://a.test", "https://b.test"]


@pytest.mark.asyncio
async def test_run_web_search_returns_normalized_results():
    fake = [
        normalize_search_hit(title="A", url="https://a.test", snippet="sa"),
    ]
    with (
        patch(
            "ly_next.tools.web_search._resolve_provider_chain",
            return_value=["duckduckgo"],
        ),
        patch(
            "ly_next.tools.web_search._search_with_provider",
            new_callable=AsyncMock,
            return_value=fake,
        ),
    ):
        provider, results, tried = await run_web_search("openclaw tools", count=3)

    assert provider == "duckduckgo"
    assert results[0]["url"] == "https://a.test"
    assert tried == ["duckduckgo"]


@pytest.mark.asyncio
async def test_run_web_search_fallback_on_empty():
    fake = [normalize_search_hit(title="B", url="https://b.test", snippet="sb")]
    calls: list[str] = []

    async def _side_effect(provider: str, *_args, **_kwargs):
        calls.append(provider)
        if provider == "duckduckgo":
            return []
        return fake

    with (
        patch(
            "ly_next.tools.web_search._resolve_provider_chain",
            return_value=["duckduckgo", "tavily"],
        ),
        patch(
            "ly_next.tools.web_search._search_with_provider",
            side_effect=_side_effect,
        ),
    ):
        provider, results, tried = await run_web_search("news", count=2)

    assert calls == ["duckduckgo", "tavily"]
    assert provider == "tavily"
    assert results[0]["url"] == "https://b.test"
    assert tried == ["duckduckgo", "tavily"]


@pytest.mark.asyncio
async def test_web_search_accepts_count_alias():
    fake = [normalize_search_hit(title="A", url="https://a.test", snippet="sa")]
    with patch(
        "ly_next.tools.web_search.run_web_search",
        new_callable=AsyncMock,
        return_value=("duckduckgo", fake, ["duckduckgo"]),
    ) as run:
        result = await web_search("test", count=2)

    run.assert_awaited_once_with(
        "test",
        2,
        allowed_domains=None,
        blocked_domains=None,
        recency_days=None,
    )
    assert result.success is True
    assert result.result["count"] == 1
    assert result.result["fetch_suggestions"] == ["https://a.test"]
    assert "text" in result.result
    assert "联网搜索" in result.result["text"]
    assert "web_fetch" in result.result["text"]


@pytest.mark.asyncio
async def test_web_search_passes_domain_filters():
    with patch(
        "ly_next.tools.web_search.run_web_search",
        new_callable=AsyncMock,
        return_value=("tavily", [], ["tavily"]),
    ) as run:
        await web_search(
            "papers",
            allowed_domains=["arxiv.org"],
            blocked_domains=["reddit.com"],
            recency_days=7,
        )

    run.assert_awaited_once_with(
        "papers",
        None,
        allowed_domains=["arxiv.org"],
        blocked_domains=["reddit.com"],
        recency_days=7,
    )


def test_format_web_search_text_empty():
    text = format_web_search_text(query="foo", provider="duckduckgo", results=[])
    assert "结果数：0" in text
    assert "未找到相关结果" in text


def test_format_web_search_text_includes_fetch_hint():
    rows = [normalize_search_hit(title="A", url="https://a.test", snippet="snippet")]
    text = format_web_search_text(query="foo", provider="duckduckgo", results=rows)
    assert "web_fetch" in text
    assert "https://a.test" in text


def test_coerce_tool_payload_prefers_text_field():
    payload = {
        "success": True,
        "result": {
            "query": "x",
            "text": "联网搜索\n关键词：x\n引擎：duckduckgo",
        },
    }
    assert coerce_tool_payload_text(payload).startswith("联网搜索")
