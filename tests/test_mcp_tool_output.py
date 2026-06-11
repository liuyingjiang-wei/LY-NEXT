from ly_next.core.tool_result_spill import coerce_tool_payload_text
from ly_next.mcp.langchain_adapter_bridge import _normalize_mcp_invoke_result


def test_normalize_mcp_invoke_result_text_blocks():
    text, is_error = _normalize_mcp_invoke_result(
        [{"type": "text", "text": "西安：晴，18°C"}]
    )
    assert is_error is False
    assert "西安" in text


def test_normalize_mcp_invoke_result_error_flag():
    text, is_error = _normalize_mcp_invoke_result(
        [{"type": "text", "text": "city not found", "isError": True}]
    )
    assert is_error is True
    assert "city not found" in text


def test_coerce_tool_payload_mcp_list_result():
    payload = {
        "success": True,
        "result": [{"type": "text", "text": "humidity 45%"}],
    }
    assert coerce_tool_payload_text(payload) == "humidity 45%"
