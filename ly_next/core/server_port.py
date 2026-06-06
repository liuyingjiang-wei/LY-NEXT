"""Resolve HTTP listen port for CLI / env / interactive startup."""

from __future__ import annotations

import os
import socket
import sys
from typing import Any

DEFAULT_LISTEN_PORT = 8000
ENV_PORT = "LY_NEXT_PORT"


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


def _is_non_interactive() -> bool:
    if os.environ.get("LY_NEXT_NO_PROMPT", "").strip().lower() in ("1", "true", "yes"):
        return True
    if os.environ.get("DOCKER_CONTAINER", "").strip() == "1":
        return True
    if not sys.stdout.isatty():
        return True
    return False


def _prompt_busy_port(port: int, host: str) -> int:
    from ly_next.core.logger import LogColors as c

    alt = find_free_port(port + 1, host=host)
    print()
    print(f"  {c.YELLOW}⚠{c.RESET}  端口 {c.BRIGHT}{port}{c.RESET} 已被占用")
    print(f"     {c.DIM}[1]{c.RESET} 仍使用 {port}（可能启动失败）")
    print(f"     {c.DIM}[2]{c.RESET} 改用 {alt}")
    print(f"     {c.DIM}[3]{c.RESET} 手动输入端口")
    while True:
        choice = input(f"  选择 {c.CYAN}[1/2/3]{c.RESET}（默认 2）: ").strip().lower()
        if choice in ("", "2"):
            return alt
        if choice == "1":
            return port
        if choice == "3":
            break
        print(f"  {c.RED}✖{c.RESET} 请输入 1、2 或 3")
    return _read_port_input(f"  监听端口: ", default=alt, host=host)


def _read_port_input(label: str, *, default: int, host: str) -> int:
    from ly_next.core.logger import LogColors as c

    while True:
        raw = input(f"{label}{c.DIM}[{default}]{c.RESET} ").strip()
        if not raw:
            port = default
        else:
            port = _parse_port(raw)
            if port is None:
                print(f"  {c.RED}✖{c.RESET} 请输入 1–65535 之间的有效端口")
                continue
        if is_port_in_use(host, port):
            return _prompt_busy_port(port, host)
        return port


def prompt_listen_port(default: int, *, host: str = "0.0.0.0") -> int:
    from ly_next.core.logger import LogColors as c

    print()
    print(f"  {c.CYAN}◆{c.RESET} {c.BRIGHT}选择监听端口{c.RESET}")
    print(f"  {c.DIM}直接回车使用默认 {default}{c.RESET}")
    return _read_port_input("  端口: ", default=default, host=host)


def resolve_startup_port(
    cli_port: int | None,
    config_port: int | None,
    *,
    host: str = "0.0.0.0",
    interactive: bool | None = None,
) -> int:
    """Priority: CLI > LY_NEXT_PORT env > (interactive prompt | config default)."""
    for candidate in (
        cli_port,
        _parse_port(os.environ.get(ENV_PORT)),
    ):
        if candidate is not None:
            return candidate

    default = _parse_port(config_port) or DEFAULT_LISTEN_PORT
    if interactive is False or _is_non_interactive():
        return default
    return prompt_listen_port(default, host=host)
