from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from ly_next.tools import host_sandbox as hs
from ly_next.tools.host_exec import host_run_command


@pytest.fixture
def host_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "userhome"
    home.mkdir()
    monkeypatch.setattr(hs.Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(hs, "host_roots", lambda: [home.resolve(strict=False)])
    return home


@pytest.mark.asyncio
async def test_host_run_command_echo(host_home: Path):
    if os.name == "nt":
        cmd = "Write-Output hello-host"
    else:
        cmd = "echo hello-host"
    out = await host_run_command(command=cmd, cwd=str(host_home))
    assert out.result["exit_code"] == 0
    assert "hello-host" in out.result["stdout"]


@pytest.mark.asyncio
async def test_host_run_command_rejects_bad_cwd(host_home: Path, tmp_path: Path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    out = await host_run_command(command="echo x", cwd=str(outside))
    assert not out.success
    assert out.error and "outside allowed roots" in out.error
