"""Normalize image payloads for OneBot v11 / NapCat (Yunzai-style base64://)."""

from __future__ import annotations

import re
from typing import Any

from ly_next.core.logger import get_logger

logger = get_logger(__name__)

_DATA_URL_RE = re.compile(r"^data:(image/[\w+.-]+);base64,(.+)$", re.DOTALL | re.IGNORECASE)


def normalize_onebot_image_file(file_ref: str) -> str:
    """
    OneBot ``image`` segment ``file`` field.

    Supports (per OneBot 11 / Yunzai OneBotv11 adapter):
    - http(s) URL
    - ``base64://...`` raw base64 payload
    - ``data:image/...;base64,...`` → converted to ``base64://``
    """
    ref = (file_ref or "").strip()
    if not ref:
        return ref
    if ref.startswith(("http://", "https://")):
        return ref
    if ref.startswith("base64://"):
        return ref
    m = _DATA_URL_RE.match(ref)
    if m:
        payload = m.group(2).strip()
        return f"base64://{payload}"
    if ref.startswith("data:"):
        # malformed data URL — best effort
        idx = ref.find("base64,")
        if idx >= 0:
            return f"base64://{ref[idx + 7 :].strip()}"
    # local path / file URI — pass through for NapCat
    if ref.startswith("file:") or (len(ref) > 2 and ref[1] == ":"):
        return ref
    logger.debug("[onebot_media] unknown image ref prefix: %s", ref[:48])
    return ref


def image_segment(url_or_file: str) -> dict[str, Any]:
    file_val = normalize_onebot_image_file(url_or_file)
    seg: dict[str, Any] = {"type": "image", "data": {"file": file_val}}
    if file_val.startswith(("http://", "https://")):
        seg["data"]["url"] = file_val
    return seg
