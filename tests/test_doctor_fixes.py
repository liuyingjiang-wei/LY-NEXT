"""Tests for doctor one-click fixes."""

from ly_next.core.doctor_fixes import apply_doctor_fix, list_doctor_fixes


def test_list_doctor_fixes():
    fixes = list_doctor_fixes()
    ids = {f["id"] for f in fixes}
    assert "sync_auth_key" in ids
    assert "disable_query_api_key" in ids


def test_apply_unknown_fix():
    result = apply_doctor_fix("not_a_real_fix")
    assert result["ok"] is False
