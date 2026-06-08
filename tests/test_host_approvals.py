from __future__ import annotations

from pathlib import Path

import pytest

from ly_next.tools import host_approvals as ha
from ly_next.tools import host_sandbox as hs
from ly_next.tools.host_files import host_delete_path


@pytest.fixture(autouse=True)
def clear_approval_store():
    ha._store.clear()
    yield
    ha._store.clear()


def test_create_and_approve_delete_flow():
    item = ha.create_approval(
        tool="host_delete_path",
        action="delete",
        summary="Delete file: /tmp/x",
        payload={"path": "/tmp/x"},
    )
    assert item.status == "pending"

    decided, err = ha.decide_approval(item.id, approve=True)
    assert err is None
    assert decided is not None
    assert decided.status == "approved"

    ok, err2 = ha.consume_approval(item.id, tool="host_delete_path", action="delete")
    assert ok is True
    assert err2 is None
    assert ha.get_approval(item.id).status == "consumed"


def test_command_needs_approval_destructive():
    assert ha.command_needs_approval("rm -rf ./build") is True
    assert ha.command_needs_approval("echo hello") is False


@pytest.mark.asyncio
async def test_host_delete_requires_approval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "userhome"
    home.mkdir()
    monkeypatch.setattr(hs.Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(hs, "host_roots", lambda: [home.resolve(strict=False)])

    f = home / "tmp.txt"
    f.write_text("x", encoding="utf-8")

    first = await host_delete_path(path=str(f))
    assert not first.success
    assert first.result.get("approval_required") is True
    approval_id = first.result["approval_id"]
    assert f.exists()

    ha.decide_approval(approval_id, approve=True)
    second = await host_delete_path(path=str(f), approval_token=approval_id)
    assert second.success
    assert not f.exists()
