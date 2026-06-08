from ly_next.core.chat_trace_log import format_messages_for_log, summarize_message_content


def test_summarize_string_content():
    assert summarize_message_content("  hello world  ") == "hello world"


def test_summarize_multimodal():
    content = [
        {"type": "text", "text": "这是什么"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
    ]
    s = summarize_message_content(content)
    assert "这是什么" in s
    assert "image" in s


def test_format_messages_for_log():
    rows = format_messages_for_log(
        [
            {"role": "system", "content": "你是助手"},
            {"role": "user", "content": "你好"},
        ]
    )
    assert len(rows) == 2
    assert rows[0].startswith("system:")
    assert "你好" in rows[1]
