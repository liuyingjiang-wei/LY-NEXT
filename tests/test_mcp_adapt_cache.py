from __future__ import annotations

from ly_next.mcp.adapt_cache import (
    load_adapted_cache,
    mcp_config_fingerprint,
    save_adapted_cache,
)


def test_mcp_adapt_cache_roundtrip(tmp_path, monkeypatch):
    from ly_next.core.config import config

    monkeypatch.setattr(config, "project_root", tmp_path)
    merged = {"weather": {"command": "uvx", "args": ["--from", "pkg", "entry"]}}
    fp = mcp_config_fingerprint(merged)
    assert load_adapted_cache(fp) is None
    save_adapted_cache(fp, merged)
    loaded = load_adapted_cache(fp)
    assert loaded == merged
    assert load_adapted_cache("other") is None
