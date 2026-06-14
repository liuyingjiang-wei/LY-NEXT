"""Resolve HTTP listen port for CLI / env / interactive startup."""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path
from typing import Any

DEFAULT_LISTEN_PORT = 8000
ENV_PORT = "LY_NEXT_PORT"
MAX_RECENT_PORTS = 8
RECENT_PORTS_FILENAME = "recent_ports.json"


def is_port_in_use(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
        return False
    except OSError:
        return True
    finally:
        sock.close()


def find_free_port(start: int, *, host: str = "0.0.0.0", max_tries: int = 32) -> int:
    for offset in range(max_tries):
        candidate = start + offset
        if 1 <= candidate <= 65535 and not is_port_in_use(host, candidate):
            return candidate
    return start


def _parse_port(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        port = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if 1 <= port <= 65535:
        return port
    return None


def _recent_ports_path() -> Path:
    from ly_next.core.config import get_data_root

    root = get_data_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / RECENT_PORTS_FILENAME


def load_recent_ports() -> list[int]:
    path = _recent_ports_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    ports: list[int] = []
    for item in data:
        port = _parse_port(item)
        if port is not None and port not in ports:
            ports.append(port)
    return ports[:MAX_RECENT_PORTS]


def remember_port(port: int) -> None:
    parsed = _parse_port(port)
    if parsed is None:
        return
    recent = [parsed, *[p for p in load_recent_ports() if p != parsed]]
    _save_recent_ports(recent[:MAX_RECENT_PORTS])


def _save_recent_ports(ports: list[int]) -> None:
    cleaned: list[int] = []
    for item in ports:
        port = _parse_port(item)
        if port is not None and port not in cleaned:
            cleaned.append(port)
    cleaned = cleaned[:MAX_RECENT_PORTS]
    path = _recent_ports_path()
    try:
        if cleaned:
            path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        elif path.is_file():
            path.unlink()
    except OSError:
        return


def remove_recent_port(port: int) -> bool:
    parsed = _parse_port(port)
    if parsed is None:
        return False
    recent = load_recent_ports()
    if parsed not in recent:
        return False
    _save_recent_ports([p for p in recent if p != parsed])
    return True


def clear_recent_ports() -> None:
    _save_recent_ports([])


def _build_port_options() -> list[int]:
    options: list[int] = []
    for port in load_recent_ports():
        if port not in options:
            options.append(port)
    return options


def _is_non_interactive() -> bool:
    if os.environ.get("LY_NEXT_NO_PROMPT", "").strip().lower() in ("1", "true", "yes"):
        return True
    if os.environ.get("DOCKER_CONTAINER", "").strip() == "1":
        return True
    return bool(not sys.stdout.isatty())


def _port_option_label(port: int, *, last_port: int | None) -> str:
    if last_port is not None and port == last_port:
        return f"{port} (上次)"
    return str(port)


def _read_port_input(label: str, *, default: int | None = None) -> int:
    from ly_next.core.logger import LogColors

    while True:
        hint = f"{LogColors.DIM}[{default}]{LogColors.RESET} " if default is not None else ""
        raw = input(f"{label}{hint}").strip()
        if not raw:
            if default is not None:
                port = default
            else:
                print(f"  {LogColors.RED}✖{LogColors.RESET} 请输入 1–65535 之间的有效端口")
                continue
        else:
            port = _parse_port(raw)
            if port is None:
                print(f"  {LogColors.RED}✖{LogColors.RESET} 请输入 1–65535 之间的有效端口")
                continue
        remember_port(port)
        return port


def _finalize_port_choice(port: int) -> int:
    remember_port(port)
    return port


def _prompt_remove_recent_ports() -> None:
    from ly_next.core.cli_select import select_option
    from ly_next.core.logger import LogColors

    while True:
        options = _build_port_options()
        if not options:
            return

        recent = load_recent_ports()
        last_port = recent[0] if recent else None
        labels = [_port_option_label(port, last_port=last_port) for port in options]
        clear_idx = len(options)
        back_idx = clear_idx + 1
        labels.append("清除全部历史端口")
        labels.append("返回")

        choice = select_option(
            labels,
            title="删除历史端口",
            hint="↑↓ 移动  Enter 确认",
            default_index=back_idx,
        )
        if choice == back_idx:
            return
        if choice == clear_idx:
            clear_recent_ports()
            print(f"\n  {LogColors.GREEN}✓{LogColors.RESET} 已清除全部历史端口\n", flush=True)
            return
        port = options[choice]
        if remove_recent_port(port):
            print(f"\n  {LogColors.GREEN}✓{LogColors.RESET} 已删除端口 {port}\n", flush=True)
        if not _build_port_options():
            return


def prompt_listen_port(*, host: str = "0.0.0.0") -> int:
    del host  # 交互选择不做占用检测，避免 0.0.0.0/127.0.0.1 误报
    from ly_next.core.cli_select import select_option

    while True:
        options = _build_port_options()
        recent = load_recent_ports()
        last_port = recent[0] if recent else None

        if not options:
            return _read_port_input("  端口: ", default=last_port)

        labels = [_port_option_label(port, last_port=last_port) for port in options]
        manual_idx = len(options)
        labels.append("手动输入端口")
        labels.append("删除历史端口…")

        hint = f"↑↓ 移动  Enter 确认  · 上次 {last_port}" if last_port else "↑↓ 移动  Enter 确认"
        choice = select_option(
            labels,
            title="选择监听端口",
            hint=hint,
            default_index=0,
        )
        if choice < len(options):
            return _finalize_port_choice(options[choice])
        if choice == manual_idx:
            return _read_port_input("  端口: ", default=last_port)
        _prompt_remove_recent_ports()


def resolve_startup_port(
    cli_port: int | None,
    config_port: int | None,
    *,
    host: str = "0.0.0.0",
    interactive: bool | None = None,
) -> int:
    """Priority: CLI > LY_NEXT_PORT env > (interactive prompt | config default)."""
    del host
    for candidate in (
        cli_port,
        _parse_port(os.environ.get(ENV_PORT)),
    ):
        if candidate is not None:
            return candidate

    if interactive is False or (interactive is not True and _is_non_interactive()):
        return _parse_port(config_port) or DEFAULT_LISTEN_PORT

    return prompt_listen_port()
