from __future__ import annotations

import pytest

from ly_next.tools.json_tools import json_query


@pytest.mark.asyncio
async def test_json_query_dot_path():
    payload = '{"items":[{"name":"a"},{"name":"b"}]}'
    result = await json_query(data=payload, path="items[1].name")
    assert result.success is True
    assert result.result["value"] == "b"


@pytest.mark.asyncio
async def test_json_query_missing_path():
    result = await json_query(data='{"x":1}', path="missing")
    assert result.success is False
