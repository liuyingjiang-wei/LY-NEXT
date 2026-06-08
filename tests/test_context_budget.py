from __future__ import annotations

from ly_next.core.context_budget import prune_old_tool_message_contents


def test_prune_protects_recent_and_summarizes_old(monkeypatch):
    monkeypatch.setattr(
        "ly_next.core.context_budget._ctx_cfg",
        lambda: {
            "prune_enabled": True,
            "prune_dialog_fill_ratio": 0.5,
            "reserve_completion_tokens": 1024,
            "prune_protect_recent_turns": 1,
            "prune_min_tool_chars": 10,
            "prune_tool_summarize": True,
            "prune_tool_head_chars": 20,
            "prune_tool_tail_chars": 10,
            "tool_placeholder": "[removed]",
        },
    )
    monkeypatch.setattr(
        "ly_next.core.context_budget.effective_context_window_tokens",
        lambda _model: 2048,
    )

    old_body = "HEAD_" + ("x" * 12000) + "_TAIL"
    messages = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "tool", "content": old_body},
        {"role": "tool", "content": "y" * 6000},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "tool", "content": "recent tool output stays"},
    ]

    out = prune_old_tool_message_contents(messages, model="test", max_output_tokens=512)
    assert out[2]["content"] != old_body
    assert "HEAD_" in out[2]["content"]
    assert "_TAIL" in out[2]["content"]
    assert out[6]["content"] == "recent tool output stays"
