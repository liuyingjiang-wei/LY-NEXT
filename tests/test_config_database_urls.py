from __future__ import annotations

import platform

from ly_next.core.config import Config


def test_iter_database_urls_skips_unix_socket_on_windows(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    c = Config.__new__(Config)
    c._config = {
        "database": {
            "host": "localhost",
            "port": 5432,
            "username": "postgres",
            "password": "",
            "database": "ly_next",
            "try_unix_socket": True,
        }
    }
    c._cache = {}
    urls = c.iter_database_urls()
    assert len(urls) == 1
    assert "127.0.0.1" in urls[0] or "localhost" in urls[0]
    assert all("?host=" not in u for u in urls)
