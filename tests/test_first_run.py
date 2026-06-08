from __future__ import annotations

from ly_next.core.first_run import (
    build_first_run_notice_body,
    read_first_run_api_key,
    sync_first_run_notice,
)


def test_sync_first_run_notice_writes_and_updates(tmp_path, monkeypatch):
    monkeypatch.setattr("ly_next.core.first_run.get_data_root", lambda: tmp_path)
    path = tmp_path / "FIRST_RUN.txt"

    assert sync_first_run_notice("key-alpha") is True
    assert path.is_file()
    assert read_first_run_api_key() == "key-alpha"
    assert "key-alpha" in path.read_text(encoding="utf-8")

    assert sync_first_run_notice("key-alpha") is False

    assert sync_first_run_notice("key-beta") is True
    assert read_first_run_api_key() == "key-beta"


def test_build_first_run_notice_body():
    body = build_first_run_notice_body("abc")
    assert "API Key: abc" in body
