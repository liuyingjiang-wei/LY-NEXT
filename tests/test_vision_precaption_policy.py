from __future__ import annotations

from ly_next.agent import vision_precaption as vp


def test_apply_failure_keep_original():
    msgs = [{"role": "user", "content": [{"type": "text", "text": "x"}]}]
    raw = {"on_failure": "keep_original"}
    out = vp._apply_precaption_failure(
        msgs,
        0,
        "x",
        raw=raw,
        prefix="P:",
        max_merged_chars=1000,
        exc=RuntimeError("x"),
    )
    assert out is msgs


def test_apply_failure_annotate():
    msgs = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    raw = {"on_failure": "annotate", "failure_note": "NOTE"}
    out = vp._apply_precaption_failure(
        msgs,
        0,
        "hi",
        raw=raw,
        prefix="P:",
        max_merged_chars=1000,
        exc=RuntimeError("x"),
    )
    assert out[0]["role"] == "user"
    assert isinstance(out[0]["content"], str)
    assert "hi" in out[0]["content"]
    assert "NOTE" in out[0]["content"]


def test_apply_failure_text_only():
    msgs = [{"role": "user", "content": [{"type": "text", "text": "only"}]}]
    raw = {"on_failure": "text_only"}
    out = vp._apply_precaption_failure(
        msgs,
        0,
        "only",
        raw=raw,
        prefix="P:",
        max_merged_chars=1000,
        exc=RuntimeError("x"),
    )
    assert out[0]["content"] == "only"
