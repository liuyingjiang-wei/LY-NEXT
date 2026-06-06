from ly_next.bridge.onebot11.cq import (
    apply_prefix_trigger,
    is_at_self,
    message_to_text,
    normalize_user_message_text,
)


def test_message_to_text_string():
    assert message_to_text("hello") == "hello"
    assert message_to_text("[CQ:at,qq=123][CQ:at,qq=all] hi") != ""


def test_message_to_text_array():
    segs = [
        {"type": "at", "data": {"qq": "123"}},
        {"type": "text", "data": {"text": " ping"}},
    ]
    assert message_to_text(segs) == "@ ping" or "ping" in message_to_text(segs)


def test_is_at_self():
    assert is_at_self("[CQ:at,qq=100]", 100)
    assert is_at_self([{"type": "at", "data": {"qq": "200"}}], 200)
    assert not is_at_self("plain", 100)


def test_prefix_trigger_empty_means_pass():
    assert apply_prefix_trigger("hello", ()) == "hello"


def test_prefix_trigger_required():
    assert apply_prefix_trigger("hello", ("/ai",)) is None
    assert apply_prefix_trigger("/ai test", ("/ai",)) == "test"


def test_normalize_user_message_text_strips_self_at():
    raw = "[CQ:at,qq=100] 你好"
    assert normalize_user_message_text(raw, 100) == "你好"
