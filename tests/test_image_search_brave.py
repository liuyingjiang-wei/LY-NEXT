import pytest

from ly_next.tools import image_search_providers as isp


@pytest.mark.asyncio
async def test_search_brave_thumbnail_as_string(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {"url": "https://main.example/a.jpg"},
                    {"thumbnail": "https://thumb.example/b.jpg"},
                    {"thumbnail": {"src": "https://thumb.example/c.jpg"}},
                ]
            }

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, *a, **k):
            return FakeResp()

    monkeypatch.setattr(isp.httpx, "AsyncClient", FakeClient)

    urls = await isp.search_brave("cats", 3, "test-key")
    assert urls == [
        "https://main.example/a.jpg",
        "https://thumb.example/b.jpg",
        "https://thumb.example/c.jpg",
    ]
