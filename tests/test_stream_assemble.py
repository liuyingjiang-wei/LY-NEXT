"""Tests for eager tool dispatch helpers."""

from __future__ import annotations

from ly_next.models.stream_assemble import (
    is_tool_call_sealed,
    parse_sealed_tool_call,
    try_parse_tool_arguments,
)


def test_try_parse_tool_arguments_incomplete():
    assert try_parse_tool_arguments('{"q": "hel') is None


def test_try_parse_tool_arguments_complete():
    assert try_parse_tool_arguments('{"q": "hello"}') == {"q": "hello"}


def test_is_tool_call_sealed():
    sealed = {
        "id": "call_1",
        "function": {"name": "web_search", "arguments": '{"query":"test"}'},
    }
    partial = {
        "id": "call_1",
        "function": {"name": "web_search", "arguments": '{"query":'},
    }
    assert is_tool_call_sealed(sealed) is True
    assert is_tool_call_sealed(partial) is False


def test_parse_sealed_tool_call():
    tc = {
        "id": "call_abc",
        "function": {"name": "read_file", "arguments": '{"path":"a.txt"}'},
    }
    assert parse_sealed_tool_call(tc) == ("read_file", {"path": "a.txt"}, "call_abc")
