"""Resolve PostgreSQL TCP port and credentials (Windows install dir vs config)."""

from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Any


def read_windows_postgresql_conf_port() -> int | None:
    """Read ``port`` from the newest PostgreSQL install under Program Files."""
    if platform.system() != "Windows":
        return None
    for env_key in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(env_key)
        if not root:
            continue
        base = Path(root) / "PostgreSQL"
        if not base.is_dir():
            continue
        ver_dirs = sorted(
            (p for p in base.iterdir() if p.is_dir()),
            key=lambda p: p.name,
            reverse=True,
        )
        for ver_dir in ver_dirs:
            for conf in (ver_dir / "data" / "postgresql.conf", ver_dir / "postgresql.conf"):
                if not conf.is_file():
                    continue
                try:
                    for line in conf.read_text(encoding="utf-8", errors="ignore").splitlines():
                        t = line.strip()
                        if t.startswith("#"):
                            continue
                        if t.startswith("port") and "=" in t:
                            val = t.split("=", 1)[1].strip().strip("'\"")
                            if val.isdigit():
                                return int(val)
                except OSError:
                    continue
    return None


def resolve_database_password(db_config: dict[str, Any] | None = None) -> str:
    """Config password, else ``POSTGRES_PASSWORD`` when config value is empty."""
    if db_config is None:
        from ly_next.core.config import config

        raw = config.get("database", {})
        db_config = raw if isinstance(raw, dict) else {}

    raw = db_config.get("password", "")
    if raw is None:
        raw = ""
    pw = str(raw).strip()
    if pw:
        return pw
    return os.environ.get("POSTGRES_PASSWORD", "").strip()


def resolve_database_port(db_config: dict[str, Any] | None = None) -> int:
    """Port used for TCP connections; on Windows prefers postgresql.conf over stale yaml."""
    if db_config is None:
        from ly_next.core.config import config

        raw = config.get("database", {})
        db_config = raw if isinstance(raw, dict) else {}

    configured = int(db_config.get("port", 5432) or 5432)
    detected = read_windows_postgresql_conf_port()
    if detected is not None and detected > 0:
        return detected
    return configured


def sync_database_port_from_install() -> bool:
    """Persist detected PostgreSQL port into user config when it differs."""
    from ly_next.core.config import config

    db = config.get("database", {})
    if not isinstance(db, dict):
        return False
    configured = int(db.get("port", 5432) or 5432)
    resolved = resolve_database_port(db)
    if resolved == configured:
        return False
    config.set("database.port", resolved, save=True)
    config.load()
    from ly_next.core.logger import get_logger

    get_logger(__name__).info(
        "已将 database.port 从 %s 同步为 %s（与 PostgreSQL 安装目录 postgresql.conf 一致）",
        configured,
        resolved,
    )
    return True
