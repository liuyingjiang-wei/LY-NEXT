"""TTY single-select menu: arrow keys + Enter (no numeric input)."""

from __future__ import annotations

import sys


def _read_key() -> str | None:
    # Windows Python has no termios — use msvcrt in cmd, PowerShell, and Git Bash alike.
    if sys.platform == "win32":
        import msvcrt

        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            if ch2 == "H":
                return "up"
            if ch2 == "P":
                return "down"
            return None
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x03":
            raise KeyboardInterrupt
        return None

    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            ch2 = sys.stdin.read(1)
            if ch2 == "[":
                ch3 = sys.stdin.read(1)
                if ch3 == "A":
                    return "up"
                if ch3 == "B":
                    return "down"
        elif ch in ("\r", "\n"):
            return "enter"
        elif ch == "\x03":
            raise KeyboardInterrupt
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return None


def _format_row(label: str, active: bool) -> str:
    from ly_next.core.logger import LogColors

    if active:
        marker = f"{LogColors.CYAN}▸{LogColors.RESET}"
        text = f"{LogColors.BRIGHT}{label}{LogColors.RESET}"
    else:
        marker = f"{LogColors.DIM} ·{LogColors.RESET}"
        text = f"{LogColors.DIM}{label}{LogColors.RESET}"
    return f"  {marker} {text}"


def _refresh_menu(
    options: list[str],
    *,
    selected: int,
    hint: str,
) -> None:
    """Rewrite option rows + hint in place (Git Bash / mintty safe)."""
    from ly_next.core.logger import LogColors

    n = len(options)
    # Cursor sits on the line after hint; move up over all options + hint row.
    sys.stdout.write(f"\033[{n + 1}A")
    for i, label in enumerate(options):
        sys.stdout.write("\033[2K\r")
        print(_format_row(label, i == selected))
    sys.stdout.write("\033[2K\r")
    print(f"  {LogColors.DIM}{hint}{LogColors.RESET}")
    sys.stdout.flush()


def select_option(
    options: list[str],
    *,
    title: str,
    hint: str = "↑↓ 移动  Enter 确认",
    default_index: int = 0,
) -> int:
    """Return selected index. Falls back to default when stdin is not a TTY."""
    if not options:
        raise ValueError("options must not be empty")
    if not sys.stdin.isatty():
        return max(0, min(default_index, len(options) - 1))

    from ly_next.core.logger import LogColors

    selected = max(0, min(default_index, len(options) - 1))

    print()
    print(f"  {LogColors.CYAN}◆{LogColors.RESET} {LogColors.BRIGHT}{title}{LogColors.RESET}")
    for i, label in enumerate(options):
        print(_format_row(label, i == selected))
    print(f"  {LogColors.DIM}{hint}{LogColors.RESET}")

    while True:
        key = _read_key()
        if key == "up":
            selected = (selected - 1) % len(options)
        elif key == "down":
            selected = (selected + 1) % len(options)
        elif key == "enter":
            print()
            return selected
        elif key is None:
            continue

        _refresh_menu(options, selected=selected, hint=hint)
