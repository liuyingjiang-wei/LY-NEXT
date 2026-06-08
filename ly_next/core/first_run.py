"""Keep data/ly_next/FIRST_RUN.txt in sync with auth.api_key."""

from __future__ import annotations

import re

from ly_next.core.config import get_data_root
from ly_next.core.logger import get_logger

logger = get_logger(__name__)

_FIRST_RUN_KEY_RE = re.compile(r"^API Key:\s*(.+?)\s*$", re.MULTILINE)


def first_run_notice_path():
    return get_data_root() / "FIRST_RUN.txt"


def read_first_run_api_key() -> str | None:
    path = first_run_notice_path()
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _FIRST_RUN_KEY_RE.search(text)
    if not match:
        return None
    key = match.group(1).strip()
    return key or None


def build_first_run_notice_body(api_key: str) -> str:
    return (
        "LY-NEXT 首次启动 — 工作台登录密钥\n"
        "================================\n\n"
        f"API Key: {api_key}\n\n"
        "用法:\n"
        "  1. 浏览器打开 /ly/login\n"
        "  2. 粘贴上方 API Key 登录\n\n"
        "此文件应与 data/ly_next/config.yaml 中 auth.api_key 一致；"
        "若在「访问控制」中更换密钥，重启服务后会自动更新本文件。\n\n"
        "生产环境请尽快更换密钥，并勿将此文件提交到版本库。\n"
    )


def sync_first_run_notice(api_key: str) -> bool:
    """Write or update FIRST_RUN.txt when missing or API key changed."""
    key = str(api_key or "").strip()
    if not key:
        return False
    path = first_run_notice_path()
    existing = read_first_run_api_key()
    if existing == key and path.is_file():
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(build_first_run_notice_body(key), encoding="utf-8")
        if existing and existing != key:
            logger.info("已更新 FIRST_RUN.txt（与 config.yaml 中的 auth.api_key 同步）")
        else:
            logger.info("已写入首次登录说明: %s", path)
        return True
    except OSError as e:
        logger.warning("无法写入 FIRST_RUN.txt: %s", e)
        return False
