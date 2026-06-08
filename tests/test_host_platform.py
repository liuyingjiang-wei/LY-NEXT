from __future__ import annotations

import os

import pytest

from ly_next.tools import host_platform as hp


def test_detect_host_platform_known():
    plat = hp.detect_host_platform()
    assert plat in ("windows", "macos", "linux", "other")


def test_default_shell_command_non_empty():
    argv = hp.default_shell_command("echo hello")
    assert len(argv) >= 2
    assert "hello" in " ".join(argv)


def test_default_shell_command_rejects_empty():
    with pytest.raises(ValueError):
        hp.default_shell_command("   ")


def test_windows_argv_shape(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(hp, "detect_host_platform", lambda: "windows")
    monkeypatch.setattr(hp.shutil, "which", lambda name: "C:\\Windows\\cmd.exe" if name == "cmd" else None)
    argv = hp.default_shell_command("dir")
    assert argv[0].endswith("cmd.exe")
    assert argv[-1] == "dir"


def test_posix_prefers_bash(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(hp, "detect_host_platform", lambda: "linux")
    monkeypatch.setattr(hp.shutil, "which", lambda name: "/bin/bash" if name == "bash" else None)
    argv = hp.default_shell_command("ls -la")
    assert argv[0] == "/bin/bash"
    assert argv[1] == "-lc"
