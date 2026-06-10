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
    recent = recent[:MAX_RECENT_PORTS]
    path = _recent_ports_path()
    try:
        path.write_text(json.dumps(recent, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return


def _build_port_options(default: int) -> list[int]:
    options: list[int] = []
    for port in load_recent_ports():
        if port not in options:
            options.append(port)
    if default not in options:
        options.append(default)
    return options


def _is_non_interactive() -> bool:
    if os.environ.get("LY_NEXT_NO_PROMPT", "").strip().lower() in ("1", "true", "yes"):
        return True
    if os.environ.get("DOCKER_CONTAINER", "").strip() == "1":
        return True
    return bool(not sys.stdout.isatty())


def _prompt_busy_port(port: int, host: str) -> int:
    from ly_next.core.logger import LogColors

    alt = find_free_port(port + 1, host=host)
    print()
    print(
        f"  {LogColors.YELLOW}⚠{LogColors.RESET}  端口 {LogColors.BRIGHT}{port}{LogColors.RESET} 已被占用"
    )
    print(f"     {LogColors.DIM}[1]{LogColors.RESET} 仍使用 {port}（可能启动失败）")
    print(f"     {LogColors.DIM}[2]{LogColors.RESET} 改用 {alt}")
    print(f"     {LogColors.DIM}[3]{LogColors.RESET} 手动输入端口")
    while True:
        choice = (
            input(f"  选择 {LogColors.CYAN}[1/2/3]{LogColors.RESET}（默认 2）: ").strip().lower()
        )
        if choice in ("", "2"):
            return alt
        if choice == "1":
            return port
        if choice == "3":
            break
        print(f"  {LogColors.RED}✖{LogColors.RESET} 请输入 1、2 或 3")
    return _read_port_input("  监听端口: ", default=alt, host=host)


def _read_port_input(label: str, *, default: int, host: str) -> int:
    from ly_next.core.logger import LogColors

    while True:
        raw = input(f"{label}{LogColors.DIM}[{default}]{LogColors.RESET} ").strip()
        if not raw:
            port = default
        else:
            port = _parse_port(raw)
            if port is None:
                print(f"  {LogColors.RED}✖{LogColors.RESET} 请输入 1–65535 之间的有效端口")
                continue
        if is_port_in_use(host, port):
            return _prompt_busy_port(port, host)
        return port


def _finalize_port_choice(port: int, host: str) -> int:
    if is_port_in_use(host, port):
        port = _prompt_busy_port(port, host)
    remember_port(port)
    return port


def prompt_listen_port(default: int, *, host: str = "0.0.0.0") -> int:
    from ly_next.core.logger import LogColors

    options = _build_port_options(default)
    recent = load_recent_ports()
    last_port = recent[0] if recent else None

    print()
    print(f"  {LogColors.CYAN}◆{LogColors.RESET} {LogColors.BRIGHT}选择监听端口{LogColors.RESET}")

    for index, port in enumerate(options, start=1):
        tags: list[str] = []
        if last_port is not None and port == last_port:
            tags.append("上次")
        if port == default and port != last_port:
            tags.append("默认")
        if is_port_in_use(host, port):
            tags.append("占用")
        tag_text = f" {LogColors.DIM}({', '.join(tags)}){LogColors.RESET}" if tags else ""
        print(f"     {LogColors.DIM}[{index}]{LogColors.RESET} {port}{tag_text}")

    custom_index = len(options) + 1
    print(f"     {LogColors.DIM}[{custom_index}]{LogColors.RESET} 手动输入端口")
    quick_default = options[0] if options else default
    print(f"  {LogColors.DIM}直接回车使用 {quick_default}{LogColors.RESET}")

    while True:
        raw = input(
            f"  选择 {LogColors.CYAN}[1-{custom_index}]{LogColors.RESET}（默认 1）: ",
        ).strip()
        if not raw:
            choice = 1
        else:
            if not raw.isdigit():
                print(f"  {LogColors.RED}✖{LogColors.RESET} 请输入 1–{custom_index} 之间的数字")
                continue
            choice = int(raw)
        if 1 <= choice <= len(options):
            return _finalize_port_choice(options[choice - 1], host)
        if choice == custom_index:
            port = _read_port_input("  端口: ", default=quick_default, host=host)
            remember_port(port)
            return port
        print(f"  {LogColors.RED}✖{LogColors.RESET} 请输入 1–{custom_index} 之间的数字")


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
    if interactive is False or (interactive is not True and _is_non_interactive()):
        return default
    return prompt_listen_port(default, host=host)
