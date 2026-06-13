"""Tests for settings apply guide."""

from ly_next.core.settings_apply_guide import (
    APPLY_IMMEDIATE,
    APPLY_NEXT_TURN,
    APPLY_RESTART,
    apply_by_root_from_patch,
    apply_mode_for_root,
    settings_apply_guide_payload,
)


def test_apply_mode_for_root():
    assert apply_mode_for_root("llm") == APPLY_NEXT_TURN
    assert apply_mode_for_root("logging") == APPLY_IMMEDIATE
    assert apply_mode_for_root("server") == APPLY_RESTART


def test_apply_by_root_from_patch():
    modes = apply_by_root_from_patch({"llm": {}, "server": {}})
    assert modes["llm"] == APPLY_NEXT_TURN
    assert modes["server"] == APPLY_RESTART


def test_settings_apply_guide_payload_shape():
    payload = settings_apply_guide_payload()
    assert "modes" in payload
    assert "roots" in payload
    assert "sections" in payload
    assert len(payload["sections"]) >= 5
