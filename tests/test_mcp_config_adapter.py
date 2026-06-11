from __future__ import annotations

import pytest

from ly_next.mcp.config_adapter import (
    _adapt_npx_args,
    _adapt_uv_run_args,
    _adapt_uvx_args,
    _guess_uvx_executable,
    _parse_uvx_probe_output,
    adapt_mcp_server_config_async,
)


def test_guess_uvx_executable_weather():
    assert _guess_uvx_executable("mcp-weather-server@latest") == "mcp_weather_server"


def test_adapt_uvx_modelscope_single_arg():
    adapted = _adapt_uvx_args(["mcp-weather-server@latest"])
    assert adapted == ["--from", "mcp-weather-server@latest", "mcp_weather_server"]


def test_adapt_uv_run_modelscope():
    adapted = _adapt_uv_run_args(["run", "mcp-weather-server@latest"])
    assert adapted == ["run", "--from", "mcp-weather-server@latest", "mcp_weather_server"]


def test_adapt_npx_single_package():
    adapted = _adapt_npx_args(["bing-cn-mcp"])
    assert adapted == ["-y", "bing-cn-mcp"]


def test_parse_uvx_probe_stderr():
    text = (
        "An executable named `mcp-weather-server` is not provided.\n"
        "The following executables are available:\n"
        "- mcp_weather_server.exe\n"
        "Use `uvx --from mcp-weather-server mcp_weather_server.exe` instead.\n"
    )
    assert _parse_uvx_probe_output(text) == "mcp_weather_server"


@pytest.mark.asyncio
async def test_adapt_mcp_server_config_async_uvx():
    cfg = {
        "command": "uvx",
        "args": ["mcp-weather-server@latest"],
    }
    out = await adapt_mcp_server_config_async("weather", cfg)
    assert out["command"] == "uvx"
    assert out["args"] == ["--from", "mcp-weather-server@latest", "mcp_weather_server"]


@pytest.mark.asyncio
async def test_adapt_skips_already_from():
    cfg = {
        "command": "uvx",
        "args": ["--from", "pkg@latest", "entry"],
    }
    out = await adapt_mcp_server_config_async("x", cfg)
    assert out["args"] == ["--from", "pkg@latest", "entry"]
