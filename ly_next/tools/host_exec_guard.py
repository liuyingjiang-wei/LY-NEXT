"""Hard blocks and minimal environment for host shell execution."""

from __future__ import annotations

import os
import re
from typing import Any

from ly_next.core.config import config

_DEFAULT_HARD_BLOCK_PATTERNS = [
    r"\|\s*(ba)?sh\b",
    r"\|\s*powershell\b",
    r"\|\s*pwsh\b",
    r"\bcurl\b[^\n\r|]*\|\s*(ba)?sh\b",
    r"\bwget\b[^\n\r|]*\|\s*(ba)?sh\b",
    r"\bInvoke-Expression\b",
    r"\biex\b",
    r"\bchmod\s+[0-7]{3,4}\s+/",
    r"\bchown\s+[^\s]+\s+/",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r":\(\)\s*\{\s*:\|:&\s*\};:",
]


def _exec_cfg() -> dict[str, Any]:
    host = config.get("tools.host") or {}
    if not isinstance(host, dict):
        return {}
    exec_cfg = host.get("exec") or {}
    return exec_cfg if isinstance(exec_cfg, dict) else {}


def hard_block_patterns() -> list[re.Pattern[str]]:
    raw = _exec_cfg().get("hard_block_patterns")
    patterns = list(_DEFAULT_HARD_BLOCK_PATTERNS)
    if isinstance(raw, list):
        for item in raw:
            text = str(item or "").strip()
            if text:
                patterns.append(text)
    out: list[re.Pattern[str]] = []
    for p in patterns:
        try:
            out.append(re.compile(p, re.IGNORECASE))
        except re.error:
            continue
    return out


def command_hard_blocked(command: str) -> str | None:
    text = str(command or "").strip()
    if not text:
        return None
    for pat in hard_block_patterns():
        if pat.search(text):
            return f"command blocked by host exec hard-block policy: {pat.pattern}"
    return None


def minimal_exec_env() -> dict[str, str] | None:
    if not bool(_exec_cfg().get("minimal_env", True)):
        return None
    allow = _exec_cfg().get("env_allowlist")
    keys = (
        [str(k).strip() for k in allow if str(k).strip()]
        if isinstance(allow, list) and allow
        else [
            "PATH",
            "PATHEXT",
            "SystemRoot",
            "WINDIR",
            "HOME",
            "USERPROFILE",
            "TEMP",
            "TMP",
            "LANG",
            "LC_ALL",
            "COMSPEC",
        ]
    )
    base = os.environ
    return {k: base[k] for k in keys if k in base}
