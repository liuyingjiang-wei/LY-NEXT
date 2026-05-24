from __future__ import annotations

from ly_next.core.service_manager import InstallStatus, ServiceManager


def test_postgres_installed_via_windows_service(monkeypatch):
    sm = ServiceManager()
    monkeypatch.setattr(sm, "_postgres_executable", lambda _name: None)
    monkeypatch.setattr(sm, "_list_windows_postgres_services", lambda: ["postgresql-x64-17"])
    assert sm._check_service_installed("postgresql") == InstallStatus.INSTALLED


def test_postgres_installed_via_program_files_bin(monkeypatch, tmp_path):
    sm = ServiceManager()
    bin_dir = tmp_path / "17" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "psql.exe").write_text("", encoding="utf-8")
    monkeypatch.setattr(sm, "_postgres_bin_dirs", lambda: [bin_dir])
    monkeypatch.setattr(sm, "_list_windows_postgres_services", lambda: [])
    assert sm._check_service_installed("postgresql") == InstallStatus.INSTALLED


def test_format_pg_error_empty_str():
    sm = ServiceManager()

    class EmptyPgError(Exception):
        pass

    err = EmptyPgError()
    assert "EmptyPgError" in sm._format_pg_error(err)
