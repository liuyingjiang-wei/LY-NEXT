from ly_next.core.config import Config


def test_sanitize_auth_whitelist_removes_workbench_paths(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
auth:
  whitelist:
    - /docs
    - /ly
    - /ly/
    - /ly/login
""".strip(),
        encoding="utf-8",
    )
    c = Config()
    monkeypatch.setattr(c, "config_file", cfg_file)
    monkeypatch.setattr(c, "default_config_file", cfg_file)
    c.load()
    wl = c.get("auth.whitelist") or []
    assert "/ly" not in wl
    assert "/ly/" not in wl
    assert "/docs" not in wl
    assert "/openapi.json" not in wl
    assert "/redoc" not in wl
    assert "/ly/login" in wl
    assert c.sanitize_auth_whitelist() == []
