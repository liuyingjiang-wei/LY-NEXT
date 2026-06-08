from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ly_next.core.config import get_data_root

_SAFE_CHARS = re.compile(r"[^\w\-.]+", re.UNICODE)


def exports_dir() -> Path:
    path = get_data_root() / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_export_filename(stem: str, ext: str) -> str:
    ext = ext.lstrip(".").lower()
    slug = _SAFE_CHARS.sub("_", (stem or "export").strip()).strip("._")[:72] or "export"
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{ts}_{uuid.uuid4().hex[:8]}_{slug}.{ext}"


def resolve_export_path(filename: str) -> Path | None:
    name = Path(str(filename or "").strip()).name
    if not name or name != filename or ".." in filename:
        return None
    path = exports_dir() / name
    if not path.is_file():
        return None
    try:
        path.resolve().relative_to(exports_dir().resolve())
    except ValueError:
        return None
    return path


def export_download_url(filename: str) -> str:
    return f"/api/exports/{filename}"
