from __future__ import annotations

import pytest

from ly_next.tools import image_gen_providers as igp


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"data": [{"url": "https://example.com/generated.png"}]}


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs) -> None:
        self.captured: dict[str, str] = kwargs.get("captured", {})

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def post(self, url: str, **kwargs) -> _FakeResponse:
        self.captured["url"] = url
        return _FakeResponse()


def _patch_config(monkeypatch: pytest.MonkeyPatch, *, llm_base_url: str) -> dict[str, str]:
    captured: dict[str, str] = {}

    def fake_get(key: str, default=None):
        if key == "tools.image":
            return {"config_ref": "openai_compat_llm"}
        if key == "openai_compat_llm":
            return {"api_key": "sk-test", "base_url": llm_base_url}
        return default

    monkeypatch.setattr(igp.config, "get", fake_get)
    monkeypatch.setattr(
        igp.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(captured=captured, **kwargs),
    )
    return captured


@pytest.mark.asyncio
async def test_generate_openai_compat_image_uses_default_base_url(monkeypatch):
    captured = _patch_config(monkeypatch, llm_base_url="")

    result = await igp.generate_openai_compat_image("a cat")

    assert result[0] == "https://example.com/generated.png"
    assert result[2] is None
    assert captured["url"] == "https://api.openai.com/v1/images/generations"


@pytest.mark.asyncio
async def test_generate_openai_compat_image_rewrites_dashscope_base_url(monkeypatch):
    captured = _patch_config(
        monkeypatch,
        llm_base_url="https://coding.dashscope.aliyuncs.com/v1",
    )

    await igp.generate_openai_compat_image("a cat")

    assert captured["url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1/images/generations"
