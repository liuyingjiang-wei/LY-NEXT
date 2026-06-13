"""Tests for ly config migrate."""

import textwrap

from ly_next.core.config import Config
from ly_next.core.config_migrate import is_self_service_llm_url, run_config_migrate


def test_is_self_service_llm_url_detects_local_8000():
    assert is_self_service_llm_url("http://127.0.0.1:8000/v1", port=8000) is True
    assert is_self_service_llm_url("http://localhost:8000/v1", port=8000) is True
    assert is_self_service_llm_url("http://127.0.0.1:11434/v1", port=8000) is False


def test_run_config_migrate_fixes_compat_url(tmp_path, monkeypatch):
    monkeypatch.setenv("LY_NEXT_CONFIG_DIR", str(tmp_path))
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        textwrap.dedent(
            """
            llm:
              default_model: openai_compat
              models:
                - name: openai_compat
                  format: openai_compat
                  model: qwen2.5
                  api_key: not-needed
                  base_url: http://127.0.0.1:8000/v1
            server:
              port: 8000
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    Config.reset_instance()
    cfg = Config()
    monkeypatch.setattr("ly_next.core.config_migrate.config", cfg)

    result = run_config_migrate(save=True, prune_legacy=True)
    assert any("base_url" in c for c in result["changes"])
    models = cfg.get("llm.models")
    compat = next(m for m in models if m["name"] == "openai_compat")
    assert compat["base_url"] == "http://127.0.0.1:11434/v1"
    Config.reset_instance()
