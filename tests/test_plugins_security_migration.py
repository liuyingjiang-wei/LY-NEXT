from __future__ import annotations

from pathlib import Path

import yaml

from ly_next.core.config import Config


def test_migrate_plugins_security_profile_when_local_plugins_exist(tmp_path: Path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    local = project / "plugins" / "local" / "demo_plugin"
    local.mkdir(parents=True)
    (local / "__init__.py").write_text("# demo\n", encoding="utf-8")

    cfg_dir = tmp_path / "data"
    cfg_dir.mkdir()
    cfg_file = cfg_dir / "config.yaml"
    cfg_file.write_text(
        yaml.safe_dump({"plugins": {"security_profile": "production", "modules": []}}),
        encoding="utf-8",
    )

    monkeypatch.setenv("LY_NEXT_PROJECT_ROOT", str(project))
    monkeypatch.setenv("LY_NEXT_CONFIG_DIR", str(cfg_dir))

    Config._instance = None
    cfg = Config()
    assert cfg.get("plugins.security_profile") == "development"

    saved = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
    assert saved["plugins"]["security_profile"] == "development"

    Config._instance = None
