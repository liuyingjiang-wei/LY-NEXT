from __future__ import annotations

import json

import pytest

from ly_next.core.doctor import format_doctor_report, gather_doctor_report, run_doctor_cli


@pytest.mark.asyncio
async def test_gather_doctor_report_shape():
    report = await gather_doctor_report()
    assert report["version"]
    assert report["maturity"] == "Alpha"
    assert "readiness" in report
    assert "security" in report
    assert isinstance(report["checks"], list)
    assert "suggestions" in report
    assert "ok_to_run" in report


def test_format_doctor_report_contains_sections():
    report = {
        "version": "1.0.1",
        "maturity": "Alpha",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "config_path": "/tmp/config.yaml",
        "readiness": {
            "ready_for_chat": False,
            "checks": {"llm": {"ok": False, "provider": "openai", "hint": "fill key"}},
        },
        "checks": [{"ok": True, "label": "test", "hint": None}],
        "security": {"checks": []},
        "suggestions": ["do something"],
        "ok_to_run": False,
    }
    text = format_doctor_report(report)
    assert "LY-NEXT doctor" in text
    assert "依赖就绪" in text
    assert "安全体检" in text
    assert "Alpha 阶段不建议公网裸奔" in text


def test_run_doctor_cli_json(capsys):
    code = run_doctor_cli(["--json"])
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["maturity"] == "Alpha"
    assert code in (0, 1)
