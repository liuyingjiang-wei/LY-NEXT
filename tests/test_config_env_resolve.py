from __future__ import annotations

import textwrap

from ly_next.core.config import Config, _resolve_env_vars
from ly_next.core.postgres_port import resolve_database_password


def test_resolve_env_placeholders():
    assert _resolve_env_vars("${REDIS_HOST:-localhost}") == "localhost"
    assert _resolve_env_vars({"host": "${REDIS_HOST:-localhost}"})["host"] == "localhost"


def test_minimal_user_config_resolves_redis_host_after_merge(tmp_path, monkeypatch):
    monkeypatch.setenv("LY_NEXT_CONFIG_DIR", str(tmp_path))
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        textwrap.dedent(
            """
            database:
              host: localhost
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    Config.reset_instance()
    c = Config()
    assert c.get("redis.host") == "localhost"
    assert "REDIS_HOST" not in str(c.redis_url)
    Config.reset_instance()


def test_database_password_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "from-env")
    assert resolve_database_password({"password": ""}) == "from-env"
    assert resolve_database_password({"password": "yaml"}) == "yaml"
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    assert resolve_database_password({"password": ""}) == ""
