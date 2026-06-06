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
    assert "/ly" not in c.get("auth.whitelist")
    assert "/ly/" not in c.get("auth.whitelist")
    assert "/ly/login" in c.get("auth.whitelist")
    assert c.sanitize_auth_whitelist() == []
