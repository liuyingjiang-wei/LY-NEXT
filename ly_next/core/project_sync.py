"""Project sync helper — inexact uv sync + plugin deps (npm-like workflow)."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from typing import Any

from ly_next.core.config import get_project_root


def run_project_sync(extra_args: list[str] | None = None, *, sync_plugins: bool = True) -> dict[str, Any]:
    """Run ``uv sync --inexact`` and optionally reinstall plugin dependencies."""
    if shutil.which("uv") is None:
        raise RuntimeError("未找到 uv 命令")

    root = get_project_root()
    cmd = ["uv", "sync", "--inexact", *(extra_args or [])]
    proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
    result: dict[str, Any] = {
        "ok": proc.returncode == 0,
        "command": " ".join(cmd),
        "stdout": (proc.stdout or "").strip() or None,
        "stderr": (proc.stderr or "").strip() or None,
        "plugin_deps": None,
    }
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(err or f"uv sync 失败 (exit {proc.returncode})")

    if sync_plugins:
        from ly_next.core.plugin_deps import sync_plugin_dependencies

        try:
            result["plugin_deps"] = sync_plugin_dependencies(install=True)
        except RuntimeError as exc:
            result["plugin_deps_error"] = str(exc)

    parts = ["已同步主项目依赖（保留插件/额外包，等同 uv sync --inexact）。"]
    plugin_msg = (result.get("plugin_deps") or {}).get("message")
    if plugin_msg:
        parts.append(plugin_msg)
    elif result.get("plugin_deps_error"):
        parts.append(f"插件依赖未更新：{result['plugin_deps_error']}")
    result["message"] = " ".join(parts)
    return result


def run_sync_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sync project deps without removing plugin packages (uv sync --inexact + plugin deps)."
    )
    parser.add_argument(
        "--no-plugin-deps",
        action="store_true",
        help="Skip ly plugins sync-deps after uv sync",
    )
    parser.add_argument(
        "uv_args",
        nargs=argparse.REMAINDER,
        help="Extra args forwarded to uv sync (after --inexact)",
    )
    args = parser.parse_args(argv)
    extra = [a for a in args.uv_args if a != "--"]
    try:
        result = run_project_sync(extra, sync_plugins=not args.no_plugin_deps)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(result.get("message") or "done")
    return 0
