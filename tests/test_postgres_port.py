from __future__ import annotations

from ly_next.core.postgres_port import resolve_database_port


def test_resolve_database_port_prefers_windows_conf(monkeypatch, tmp_path):
    pg_root = tmp_path / "PostgreSQL" / "17" / "data"
    pg_root.mkdir(parents=True)
    (pg_root / "postgresql.conf").write_text("port = 5433\n", encoding="utf-8")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.setattr("platform.system", lambda: "Windows")

    port = resolve_database_port({"port": 5432})
    assert port == 5433


def test_resolve_database_port_uses_config_when_no_conf(monkeypatch):
    monkeypatch.setattr(
        "ly_next.core.postgres_port.read_windows_postgresql_conf_port", lambda: None
    )
    assert resolve_database_port({"port": 5432}) == 5432
