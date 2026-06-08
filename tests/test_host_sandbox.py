from __future__ import annotations

from pathlib import Path

import pytest

from ly_next.tools import host_sandbox as hs


@pytest.fixture
def host_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "userhome"
    home.mkdir()
    (home / "docs").mkdir()
    (home / "docs" / "a.txt").write_text("hello", encoding="utf-8")
    monkeypatch.setattr(hs.Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(
        hs,
        "host_roots",
        lambda: [home.resolve(strict=False)],
    )
    return home


def test_resolve_relative_under_home(host_home: Path):
    got, err = hs.resolve_host_path("docs/a.txt", must_exist=True)
    assert err is None
    assert got is not None
    assert got.name == "a.txt"


def test_resolve_absolute_under_home(host_home: Path):
    target = host_home / "docs" / "a.txt"
    got, err = hs.resolve_host_path(str(target), must_exist=True)
    assert err is None
    assert got == target.resolve()


def test_reject_outside_home(host_home: Path, tmp_path: Path):
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    got, err = hs.resolve_host_path(str(outside), must_exist=True)
    assert got is None
    assert err and "outside allowed roots" in err


def test_reject_parent_traversal(host_home: Path):
    got, err = hs.resolve_host_path("../", must_exist=True)
    assert got is None
    assert err is not None


def test_deny_paths(host_home: Path, monkeypatch: pytest.MonkeyPatch):
    secret = host_home / "secret"
    secret.mkdir()
    (secret / "key.txt").write_text("k", encoding="utf-8")
    monkeypatch.setattr(hs, "_deny_prefixes", lambda: [secret.resolve(strict=False)])
    got, err = hs.resolve_host_path("secret/key.txt", must_exist=True)
    assert got is None
    assert err and "denied" in err
