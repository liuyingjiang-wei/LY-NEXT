from ly_next.tools.image_search_providers import _collect_tavily_image_urls


def test_collect_tavily_image_urls_top_level():
    data = {
        "images": ["https://a.com/1.jpg", {"url": "https://b.com/2.jpg"}],
        "results": [],
    }
    assert _collect_tavily_image_urls(data, limit=3) == [
        "https://a.com/1.jpg",
        "https://b.com/2.jpg",
    ]


def test_collect_tavily_image_urls_from_results():
    data = {
        "images": [],
        "results": [{"images": ["https://c.com/3.jpg"]}],
    }
    assert _collect_tavily_image_urls(data, limit=2) == ["https://c.com/3.jpg"]
