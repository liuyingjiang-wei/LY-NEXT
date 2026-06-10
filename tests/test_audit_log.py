import json

from ly_next.core.audit_log import audit_tool_call, write_audit_event
from ly_next.core.auth_context import bind_principal, release_principal
from ly_next.core.auth_principal import Principal


def test_audit_log_writes_json_line(tmp_path, monkeypatch):
    audit_file = tmp_path / "security_audit.log"
    monkeypatch.setattr(
        "ly_next.core.audit_log._audit_path",
        lambda: audit_file,
    )
    monkeypatch.setattr(
        "ly_next.core.audit_log.audit_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "ly_next.core.audit_log._audit_cfg",
        lambda: {"enabled": True, "log_tool_calls": True, "log_auth_events": True},
    )

    token = bind_principal(Principal("alice", "operator", "jwt"))
    try:
        audit_tool_call("calculator", {"expr": "1+1"}, {"success": True, "result": 2})
    finally:
        release_principal(token)

    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["event"] == "tool_call"
    assert row["tool"] == "calculator"
    assert row["subject"] == "alice"


def test_audit_redacts_secrets(tmp_path, monkeypatch):
    audit_file = tmp_path / "security_audit.log"
    monkeypatch.setattr("ly_next.core.audit_log._audit_path", lambda: audit_file)
    monkeypatch.setattr("ly_next.core.audit_log.audit_enabled", lambda: True)
    monkeypatch.setattr(
        "ly_next.core.audit_log._audit_cfg",
        lambda: {"enabled": True, "log_auth_events": True},
    )
    write_audit_event("login_failed", api_key="should-not-appear")
    row = json.loads(audit_file.read_text(encoding="utf-8").strip())
    assert row["event"] == "login_failed"
