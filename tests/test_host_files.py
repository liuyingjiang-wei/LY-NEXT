from __future__ import annotations

from pathlib import Path

import pytest

from ly_next.tools import host_approvals as ha
from ly_next.tools import host_sandbox as hs
from ly_next.tools.host_files import host_delete_path, host_list_dir, host_read_file, host_write_file


@pytest.fixture(autouse=True)
def clear_approval_store():
    ha._store.clear()
    yield
    ha._store.clear()


@pytest.fixture
def host_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "userhome"
    home.mkdir()
    monkeypatch.setattr(hs.Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(hs, "host_roots", lambda: [home.resolve(strict=False)])
    return home


@pytest.mark.asyncio
async def test_host_read_write_roundtrip(host_home: Path):
    target = host_home / "notes.txt"
    w = await host_write_file(path=str(target), content="line1\nline2")
    assert w.success

    r = await host_read_file(path=str(target))
    assert r.success
    assert r.result["content"] == "line1\nline2"


@pytest.mark.asyncio
async def test_host_list_dir(host_home: Path):
    (host_home / "a.txt").write_text("a", encoding="utf-8")
    (host_home / "subdir").mkdir()
    out = await host_list_dir(path=str(host_home))
    assert out.success
    names = {e["name"] for e in out.result["entries"]}
    assert "a.txt" in names
    assert "subdir" in names


@pytest.mark.asyncio
async def test_host_delete_file_with_approval(host_home: Path):
    f = host_home / "tmp.txt"
    f.write_text("x", encoding="utf-8")
    pending = await host_delete_path(path=str(f))
    assert not pending.success
    token = pending.result["approval_id"]
    ha.decide_approval(token, approve=True)
    out = await host_delete_path(path=str(f), approval_token=token)
    assert out.success
    assert not f.exists()
