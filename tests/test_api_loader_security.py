from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from ly_next.api.loader import APILoader
from ly_next.api.loader_security import sha256_file, trusted_hashes_map


def test_sha256_file_roundtrip(tmp_path: Path):
    p = tmp_path / "x.txt"
    p.write_bytes(b"hello")
    h = sha256_file(p)
    assert len(h) == 64
    assert h == sha256_file(p)


def test_trusted_hashes_map_normalizes_keys():
    with patch(
        "ly_next.api.loader_security.config.get",
        return_value={"a/b.py": "ABCD", "": "x", "y": ""},
    ):
        m = trusted_hashes_map()
    assert m == {"a/b.py": "abcd"}


def test_load_apis_production_profile_skips_loading():
    with (
        patch("ly_next.api.loader.security_profile", return_value="production"),
        patch(
            "ly_next.api.loader.config.get",
            side_effect=lambda k, d=None: True if k == "api.auto_load" else d,
        ),
    ):
        loader = APILoader()
        reg = loader.load_apis()
    assert reg.list_apis() == []


def test_load_apis_respects_auto_load_false():
    with (
        patch("ly_next.api.loader.security_profile", return_value="development"),
        patch(
            "ly_next.api.loader.config.get",
            side_effect=lambda k, d=None: False if k == "api.auto_load" else d,
        ),
    ):
        loader = APILoader()
        reg = loader.load_apis()
    assert reg.list_apis() == []
