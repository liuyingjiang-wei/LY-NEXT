"""Tests for MCP block preflight."""

import pytest

from ly_next.mcp.block_preflight import preflight_mcp_block, validate_mcp_block_body


def test_validate_empty_body():
    servers, errors = validate_mcp_block_body({})
    assert not servers
    assert errors


def test_validate_stdio_block():
    body = {
        "config": {
            "mcpServers": {
                "w": {"command": "uvx", "args": ["mcp_weather_server"]},
            }
        }
    }
    servers, errors = validate_mcp_block_body(body)
    assert not errors
    assert "w" in servers


@pytest.mark.asyncio
async def test_preflight_stdio_runtime_check():
    body = {
        "config": {
            "mcpServers": {
                "bing": {"command": "npx", "args": ["-y", "some-mcp"]},
            }
        }
    }
    result = await preflight_mcp_block(body, probe_http=False)
    assert result["server_count"] == 1
    assert isinstance(result["checks"], list)
