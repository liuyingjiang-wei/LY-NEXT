"""Path sandbox for host filesystem and shell tools."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from ly_next.core.config import config


def host_tools_enabled() -> bool:
    return bool(config.get("tools.host.enabled", False))


def host_exec_enabled() -> bool:
    host = config.get("tools.host", {}) or {}
    if not isinstance(host, dict):
        return host_tools_enabled()
    exec_cfg = host.get("exec", {}) or {}
    if not isinstance(exec_cfg, dict):
        return host_tools_enabled()
    if "enabled" in exec_cfg:
        return bool(exec_cfg.get("enabled"))
    return host_tools_enabled()


def _expand_root(raw: str) -> Path:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("empty root path")
    return Path(text).expanduser().resolve(strict=False)


def host_roots() -> list[Path]:
    raw = config.get("tools.host.roots")
    if raw is None:
        return [_default_home_root()]
    if not isinstance(raw, list) or not raw:
        return [_default_home_root()]
    roots: list[Path] = []
    for item in raw:
        try:
            roots.append(_expand_root(str(item)))
        except OSError:
            continue
    return roots or [_default_home_root()]


def _default_home_root() -> Path:
    return Path.home().resolve(strict=False)


def _deny_prefixes() -> list[Path]:
    raw = config.get("tools.host.deny_paths") or []
    if not isinstance(raw, list):
        return []
    out: list[Path] = []
    for item in raw:
        text = str(item or "").strip()
        if not text:
            continue
        try:
            out.append(Path(text).expanduser().resolve(strict=False))
        except OSError:
            continue
    return out


def _path_under_root(path: Path, root: Path) -> bool:
    root_real = root.resolve(strict=False)
    path_real = path.resolve(strict=False)
    try:
        path_real.relative_to(root_real)
        return True
    except ValueError:
        return False


def _is_denied(path: Path) -> bool:
    real = path.resolve(strict=False)
    return any(_path_under_root(real, denied) or real == denied for denied in _deny_prefixes())


def resolve_host_path(
    path: str,
    *,
    must_exist: bool = False,
    allow_create_parent: bool = False,
) -> tuple[Path | None, str | None]:
    """Resolve a user path under configured host roots."""
    text = str(path or "").strip()
    if not text:
        return None, "path is required"

    roots = host_roots()
    if not roots:
        return None, "no host roots configured"

    try:
        raw = Path(text).expanduser()
        if raw.is_absolute():
            candidate = raw.resolve(strict=False)
        else:
            candidate = (roots[0] / raw).resolve(strict=False)
    except OSError as exc:
        return None, f"cannot resolve path: {exc}"

    if not any(_path_under_root(candidate, root) for root in roots):
        return None, f"path outside allowed roots: {candidate}"

    if _is_denied(candidate):
        return None, f"path is denied by tools.host.deny_paths: {candidate}"

    if must_exist and not candidate.exists():
        return None, f"path does not exist: {candidate}"

    if allow_create_parent:
        parent = candidate.parent
        if parent and not parent.exists():
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                return None, f"cannot create parent directory: {exc}"
            if not any(_path_under_root(parent.resolve(strict=False), root) for root in roots):
                return None, "parent path outside allowed roots"

    return candidate, None


def resolve_host_cwd(cwd: str | None) -> tuple[Path | None, str | None]:
    if cwd is None or not str(cwd).strip():
        default = config.get("tools.host.exec.default_cwd")
        if default is not None and str(default).strip():
            return resolve_host_path(str(default), must_exist=True)
        home = _default_home_root()
        return home, None
    return resolve_host_path(str(cwd), must_exist=True)


def host_int_limit(key: str, default: int, *, minimum: int, maximum: int) -> int:
    raw: Any = config.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def host_exec_timeout_seconds() -> float:
    host = config.get("tools.host", {}) or {}
    exec_cfg = host.get("exec", {}) if isinstance(host, dict) else {}
    raw = exec_cfg.get("timeout_seconds", 300) if isinstance(exec_cfg, dict) else 300
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 300.0
    return max(1.0, min(value, 3600.0))


def host_exec_max_output_chars() -> int:
    host = config.get("tools.host", {}) or {}
    exec_cfg = host.get("exec", {}) if isinstance(host, dict) else {}
    default = 120_000
    if isinstance(exec_cfg, dict) and exec_cfg.get("max_output_chars") is not None:
        with contextlib.suppress(TypeError, ValueError):
            default = int(exec_cfg.get("max_output_chars"))
    return host_int_limit(
        "tools.host.exec.max_output_chars", default, minimum=1024, maximum=500_000
    )


def default_shell_command(command: str) -> list[str]:
    from ly_next.tools.host_platform import default_shell_command as _build

    return _build(command)
