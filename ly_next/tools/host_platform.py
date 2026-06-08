"""Cross-platform shell for host tools."""

from __future__ import annotations

import os
import platform
import shutil
import sys
from typing import Literal

HostPlatform = Literal["windows", "macos", "linux", "other"]


def detect_host_platform() -> HostPlatform:
    if sys.platform == "win32" or os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return "other"


def platform_label() -> str:
    plat = detect_host_platform()
    return f"{plat} ({platform.system()} {platform.release()})"


def default_shell_command(command: str) -> list[str]:
    """Build argv for a login-style shell that runs ``command``."""
    text = str(command or "").strip()
    if not text:
        raise ValueError("empty command")

    plat = detect_host_platform()
    if plat == "windows":
        return _windows_shell_argv(text)
    return _posix_shell_argv(text, prefer_bash=plat in ("macos", "linux", "other"))


def _windows_shell_argv(command: str) -> list[str]:
    for name in ("pwsh", "powershell"):
        shell = shutil.which(name)
        if shell:
            return [shell, "-NoProfile", "-NonInteractive", "-Command", command]
    cmd = shutil.which("cmd")
    if cmd:
        return [cmd, "/c", command]
    raise OSError("no shell found on Windows (pwsh, powershell, or cmd)")


def _posix_shell_argv(command: str, *, prefer_bash: bool) -> list[str]:
    if prefer_bash:
        bash = shutil.which("bash")
        if bash:
            return [bash, "-lc", command]
    sh = shutil.which("sh") or "/bin/sh"
    return [sh, "-lc", command]
