#!/usr/bin/env python3
"""Merge database/redis (and related) settings into data/ly_next/config.yaml."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml


def _merge_dict(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge_dict(out[key], value)
        else:
            out[key] = value
    return out


def _bootstrap_config(repo: Path, cfg_file: Path) -> None:
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    if cfg_file.is_file():
        return
    for candidate in (
        repo / "config" / "default_config.yaml",
        repo / "ly_next" / "default_config.yaml",
    ):
        if candidate.is_file():
            shutil.copy2(candidate, cfg_file)
            return
    cfg_file.write_text("{}\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Write local LY-NEXT service settings into config.yaml")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--patch-json", default="", help="JSON object to deep-merge into config")
    parser.add_argument("--patch-file", type=Path, default=None, help="UTF-8 JSON file (preferred on Windows)")
    args = parser.parse_args()

    repo = args.repo_root.resolve()
    cfg_file = repo / "data" / "ly_next" / "config.yaml"
    _bootstrap_config(repo, cfg_file)

    data: dict[str, Any] = {}
    if cfg_file.is_file():
        loaded = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded

    raw = "{}"
    if args.patch_file is not None:
        raw = args.patch_file.read_text(encoding="utf-8")
    elif args.patch_json:
        raw = args.patch_json

    try:
        patch = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"invalid patch JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(patch, dict):
        print("--patch-json must be a JSON object", file=sys.stderr)
        return 1

    merged = _merge_dict(data, patch)
    cfg_file.write_text(
        yaml.dump(merged, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    print(cfg_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
