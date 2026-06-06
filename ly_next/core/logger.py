import asyncio
import copy
import json
import logging
import shutil
import sys
import textwrap
import unicodedata
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from ly_next.core.config import config, get_project_root


class LogColors:
    RESET = "\033[0m"
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    BRIGHT = "\033[1m"
    DIM = "\033[2m"

    @staticmethod
    def hex(hex_color: str) -> str:
        hex_color = hex_color.lstrip("#")
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        return f"\033[38;2;{r};{g};{b}m"


COLOR_SCHEMES = {
    "default": ["#3494E6", "#3498db", "#00b4d8", "#0077b6", "#023e8a"],
    "warm": ["#FF512F", "#F09819", "#FF8008", "#FD746C", "#FE9A8B"],
    "cool": ["#00CED1", "#20B2AA", "#48D1CC", "#008B8B", "#5F9EA0"],
    "purple": ["#8A2BE2", "#9370DB", "#7B68EE", "#6A5ACD", "#483D8B"],
    "green": ["#11998e", "#38ef7d", "#56ab2f", "#a8e063", "#76b852"],
    "pink": ["#FF69B4", "#FF1493", "#C71585", "#DB7093", "#FFC0CB"],
    "rainbow": ["#FF0000", "#FF7F00", "#FFFF00", "#00FF00", "#0000FF", "#4B0082", "#9400D3"],
}

LOG_STYLES = {
    "trace": {"symbol": "·", "color": "DIM"},
    "debug": {"symbol": "◎", "color": "CYAN"},
    "info": {"symbol": "●", "color": "BLUE"},
    "warn": {"symbol": "⚠", "color": "YELLOW"},
    "warning": {"symbol": "⚠", "color": "YELLOW"},
    "error": {"symbol": "✖", "color": "RED"},
    "critical": {"symbol": "‼", "color": "RED"},
    "success": {"symbol": "✓", "color": "GREEN"},
    "mark": {"symbol": "◆", "color": "MAGENTA"},
    "tip": {"symbol": "→", "color": "YELLOW"},
    "done": {"symbol": "✓", "color": "GREEN"},
    "start": {"symbol": "▶", "color": "CYAN"},
    "stop": {"symbol": "■", "color": "YELLOW"},
    "network": {"symbol": "⇄", "color": "CYAN"},
}


def create_gradient_text(text: str, colors: list[str] = None) -> str:
    if not text:
        return text

    if colors is None:
        colors = COLOR_SCHEMES["default"]

    result = ""
    step = max(1, len(text) // len(colors))

    for i, char in enumerate(text):
        color_index = min(i // step, len(colors) - 1)
        result += LogColors.hex(colors[color_index]) + char

    return result + LogColors.RESET


def format_timestamp(console_mode: bool = True) -> str:
    now = datetime.now()
    if console_mode:
        return now.strftime("%m-%d %H:%M:%S")
    return now.strftime("%Y-%m-%d %H:%M:%S")


class EnhancedLogger:
    def __init__(self, logger: logging.Logger, scheme: str = "default"):
        self._logger = logger
        self._scheme = COLOR_SCHEMES.get(scheme, COLOR_SCHEMES["default"])
        self._timers: dict[str, float] = {}

    def _get_log_header(self) -> str:
        header_text = "[LY-Next]"
        return create_gradient_text(header_text, self._scheme)

    def _format_message(self, level: str, message: str) -> str:
        style = LOG_STYLES.get(level, LOG_STYLES["info"])
        header = self._get_log_header()

        color_map = {
            "DIM": LogColors.DIM,
            "CYAN": LogColors.CYAN,
            "BLUE": LogColors.BLUE,
            "YELLOW": LogColors.YELLOW,
            "RED": LogColors.RED,
            "GREEN": LogColors.GREEN,
            "MAGENTA": LogColors.MAGENTA,
        }

        symbol_color = color_map.get(style["color"], LogColors.RESET)
        symbol = f"{symbol_color}{style['symbol']}{LogColors.RESET}"

        return f"{header} {symbol} {message}"

    def _log(self, level: str, message: str, *args, **kwargs):
        formatted = self._format_message(level, str(message))
        log_method = getattr(self._logger, level if level != "mark" else "info")
        log_method(formatted, *args, **kwargs)

    def debug(self, message: str, *args, **kwargs):
        self._log("debug", message, *args, **kwargs)

    def info(self, message: str, *args, **kwargs):
        self._log("info", message, *args, **kwargs)

    def warning(self, message: str, *args, **kwargs):
        self._log("warning", message, *args, **kwargs)

    def warn(self, message: str, *args, **kwargs):
        self._log("warning", message, *args, **kwargs)

    def error(self, message: str, *args, **kwargs):
        self._log("error", message, *args, **kwargs)

    def exception(self, message: str, *args, **kwargs):
        exc_info = kwargs.pop("exc_info", True)
        formatted = self._format_message("error", str(message))
        self._logger.error(formatted, *args, exc_info=exc_info, **kwargs)

    def critical(self, message: str, *args, **kwargs):
        self._log("critical", message, *args, **kwargs)

    def success(self, message: str, *args, **kwargs):
        formatted = self._format_message("success", f"{LogColors.GREEN}{message}{LogColors.RESET}")
        self._logger.info(formatted, *args, **kwargs)

    def mark(self, message: str, *args, **kwargs):
        formatted = self._format_message("mark", f"{LogColors.MAGENTA}{message}{LogColors.RESET}")
        self._logger.info(formatted, *args, **kwargs)

    def tip(self, message: str, *args, **kwargs):
        formatted = self._format_message("tip", f"{LogColors.YELLOW}{message}{LogColors.RESET}")
        self._logger.info(formatted, *args, **kwargs)

    def title(self, text: str, color: str = "YELLOW"):
        header = self._get_log_header()
        timestamp = format_timestamp()
        color_code = getattr(LogColors, color, LogColors.YELLOW)

        line = "═" * (len(text) + 10)
        print(f"{header} {LogColors.DIM}[{timestamp}]{LogColors.RESET} {color_code}╔{line}╗")
        print(
            f"{header} {LogColors.DIM}[{timestamp}]{LogColors.RESET} {color_code}║     {text}     ║"
        )
        print(f"{header} {LogColors.DIM}[{timestamp}]{LogColors.RESET} {color_code}╚{line}╝")

    def subtitle(self, text: str, color: str = "CYAN"):
        header = self._get_log_header()
        timestamp = format_timestamp()
        color_code = getattr(LogColors, color, LogColors.CYAN)

        print(
            f"{header} {LogColors.DIM}[{timestamp}]{LogColors.RESET} {color_code}┌─── {text} ───┐"
        )

    def line(self, char: str = "─", length: int = 40, color: str = "DIM"):
        header = self._get_log_header()
        timestamp = format_timestamp()
        color_code = getattr(LogColors, color, LogColors.DIM)

        print(
            f"{header} {LogColors.DIM}[{timestamp}]{LogColors.RESET} {color_code}{char * length}{LogColors.RESET}"
        )

    def box(self, text: str, color: str = "BLUE"):
        header = self._get_log_header()
        timestamp = format_timestamp()
        color_code = getattr(LogColors, color, LogColors.BLUE)

        padding = 2
        padded_text = " " * padding + text + " " * padding
        line = "─" * len(padded_text)

        print(f"{header} {LogColors.DIM}[{timestamp}]{LogColors.RESET} {color_code}┌{line}┐")
        print(f"{header} {LogColors.DIM}[{timestamp}]{LogColors.RESET} {color_code}│{padded_text}│")
        print(f"{header} {LogColors.DIM}[{timestamp}]{LogColors.RESET} {color_code}└{line}┘")

    def progress(self, current: int, total: int, length: int = 30):
        header = self._get_log_header()
        timestamp = format_timestamp()

        percent = min(round((current / total) * 100), 100)
        filled_length = round((current / total) * length)
        bar = "█" * filled_length + "░" * (length - filled_length)

        message = f"{LogColors.CYAN}[{LogColors.GREEN}{bar}{LogColors.CYAN}]{LogColors.YELLOW} {percent}%{LogColors.RESET} {current}/{total}"
        print(f"{header} {LogColors.DIM}[{timestamp}]{LogColors.RESET} {message}")

    def status(self, message: str, status: str, status_color: str = "GREEN"):
        header = self._get_log_header()
        timestamp = format_timestamp()

        status_icons = {
            "success": "✓",
            "error": "✗",
            "warning": "⚠",
            "info": "ℹ",
            "pending": "⏳",
            "running": "⚙",
            "complete": "✓",
            "failed": "✗",
            "network": "⇄",
        }

        icon = status_icons.get(status.lower(), "•")
        color_code = getattr(LogColors, status_color, LogColors.GREEN)

        print(
            f"{header} {LogColors.DIM}[{timestamp}]{LogColors.RESET} {color_code}{icon} [{status.upper()}]{LogColors.RESET} {message}"
        )

    def list(self, items: list[str], title: str = None):
        header = self._get_log_header()
        timestamp = format_timestamp()

        if title:
            print(
                f"{header} {LogColors.DIM}[{timestamp}]{LogColors.RESET} {LogColors.CYAN}═══ {title} ═══{LogColors.RESET}"
            )

        for i, item in enumerate(items, 1):
            bullet = f"{LogColors.DIM}{i}.{LogColors.RESET}"
            print(f"{header} {LogColors.DIM}[{timestamp}]{LogColors.RESET}   {bullet} {item}")

    def gradient_line(self, char: str = "─", length: int = 50):
        header = self._get_log_header()
        timestamp = format_timestamp()

        gradient_text = create_gradient_text(char * length, self._scheme)
        print(f"{header} {LogColors.DIM}[{timestamp}]{LogColors.RESET} {gradient_text}")

    def gradient_text(self, text: str) -> str:
        return create_gradient_text(text, self._scheme)

    def time(self, label: str = "default"):
        self._timers[label] = datetime.now().timestamp()

    def time_end(self, label: str = "default"):
        if label in self._timers:
            duration = datetime.now().timestamp() - self._timers[label]
            if duration < 1:
                time_str = f"{duration * 1000:.0f}ms"
            elif duration < 60:
                time_str = f"{duration:.3f}s"
            else:
                minutes = int(duration // 60)
                seconds = duration % 60
                time_str = f"{minutes}m {seconds:.3f}s"

            self.info(
                f"Timer {LogColors.CYAN}{label}{LogColors.RESET}: {LogColors.YELLOW}{time_str}{LogColors.RESET}"
            )
            del self._timers[label]
        else:
            self.warning(f"Timer {label} does not exist")


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        if ts.endswith("+00:00"):
            ts = ts[:-6] + "Z"
        payload: dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "file": getattr(record, "filename", "") or "",
            "lineno": record.lineno,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info).strip()
        return json.dumps(payload, ensure_ascii=False)


class ColoredFormatter(logging.Formatter):
    LEVEL_COLORS = {
        "DEBUG": LogColors.CYAN,
        "INFO": LogColors.GREEN,
        "WARNING": LogColors.YELLOW,
        "ERROR": LogColors.RED,
        "CRITICAL": LogColors.MAGENTA + LogColors.BRIGHT,
    }

    LEVEL_ICONS = {
        "DEBUG": "◎",
        "INFO": "●",
        "WARNING": "⚠",
        "ERROR": "✖",
        "CRITICAL": "‼",
    }

    ACCESS_ICON = "⇢"

    def __init__(self, *, access: bool = False, **kwargs):
        super().__init__(**kwargs)
        self._access = access

    def format(self, record: logging.LogRecord) -> str:
        original = record.levelname
        color = self.LEVEL_COLORS.get(original, LogColors.RESET)
        if self._access:
            icon = self.ACCESS_ICON
            label = "ACCESS"
        else:
            icon = self.LEVEL_ICONS.get(original, "•")
            label = original
        padded = f"{icon} {label:<7}"
        record.levelname = f"{color}{padded}{LogColors.RESET}"
        try:
            return super().format(record)
        finally:
            record.levelname = original


class UvicornConsoleFormatter(ColoredFormatter):
    """Uvicorn / Starlette console lines with the same icon + color scheme."""

    def __init__(self, access: bool = False):
        super().__init__(
            fmt="%(asctime)s │ %(levelname)s │ %(message)s",
            datefmt="%H:%M:%S",
            access=access,
        )


class UvicornAccessFormatter(UvicornConsoleFormatter):
    def __init__(self):
        super().__init__(access=True)


class UnifiedHeaderFormatter(logging.Formatter):
    CONSOLE_FORMAT = "%(asctime)s │ %(levelname)s │ %(message)s"
    FILE_FORMAT = "%(asctime)s │ %(levelname)-8s │ %(name)s │ %(filename)s:%(lineno)d │ %(message)s"
    DATE_FORMAT = "%H:%M:%S"
    FILE_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.show_module = kwargs.get("show_module", True)
        self.show_filename = kwargs.get("show_filename", True)


_enhanced_logger: EnhancedLogger | None = None


def _std_level_from_name(name: str) -> int:
    n = (name or "info").strip().lower()
    if n == "trace":
        return logging.DEBUG
    return getattr(logging, n.upper(), logging.INFO)


def setup_logging(
    name: str = "ly_next",
    level: str | None = None,
    log_file: str | None = None,
    header: str | None = "LY-Next",
    color_scheme: str = "default",
) -> EnhancedLogger:
    global _enhanced_logger

    logger = logging.getLogger(name)

    if logger.handlers and _enhanced_logger:
        return _enhanced_logger

    log_level = level or config.get("logging.level", "info")
    logger.setLevel(_std_level_from_name(log_level))
    logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_formatter = ColoredFormatter(
        fmt=UnifiedHeaderFormatter.CONSOLE_FORMAT,
        datefmt=UnifiedHeaderFormatter.DATE_FORMAT,
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    log_path = log_file or config.get("logging.file", "logs/app.log")
    if not Path(log_path).is_absolute():
        log_path = get_project_root() / log_path

    Path(log_path).parent.mkdir(parents=True, exist_ok=True)

    max_bytes = config.get("logging.max_bytes", 10 * 1024 * 1024)
    backup_count = config.get("logging.backup_count", 5)

    file_handler = RotatingFileHandler(
        log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    if bool(config.get("logging.structured_file", False)):
        file_handler.setFormatter(JsonLineFormatter())
    else:
        file_handler.setFormatter(
            logging.Formatter(
                UnifiedHeaderFormatter.FILE_FORMAT, datefmt=UnifiedHeaderFormatter.FILE_DATE_FORMAT
            )
        )
    logger.addHandler(file_handler)

    _enhanced_logger = EnhancedLogger(logger, color_scheme)
    _reduce_third_party_log_noise()
    return _enhanced_logger


def _reduce_third_party_log_noise() -> None:
    for name in (
        "websockets",
        "websockets.server",
        "websockets.client",
        "websockets.protocol",
        "websockets.asyncio",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)
    for prefix in ("uvicorn", "starlette"):
        for existing in list(logging.root.manager.loggerDict.keys()):
            if isinstance(existing, str) and existing.startswith(prefix):
                logging.getLogger(existing).setLevel(logging.INFO)
    for existing in list(logging.root.manager.loggerDict.keys()):
        if isinstance(existing, str) and "websocket" in existing.lower():
            logging.getLogger(existing).setLevel(logging.WARNING)


def refresh_ly_next_log_level_from_config() -> None:
    logging.getLogger("ly_next").setLevel(_std_level_from_name(config.get("logging.level", "info")))
    _reduce_third_party_log_noise()


def get_uvicorn_log_config() -> dict[str, Any]:
    """Align uvicorn console lines with app logging (time │ icon level │ message)."""
    import uvicorn.config as uvconf

    cfg = copy.deepcopy(uvconf.LOGGING_CONFIG)
    cfg["formatters"]["default"] = {
        "()": "ly_next.core.logger.UvicornConsoleFormatter",
    }
    cfg["formatters"]["access"] = {
        "()": "ly_next.core.logger.UvicornAccessFormatter",
    }
    cfg["handlers"]["default"]["stream"] = "ext://sys.stdout"
    cfg["loggers"]["uvicorn.error"] = {
        "handlers": ["default"],
        "level": "INFO",
        "propagate": False,
    }
    return cfg


def get_logger(name: str) -> EnhancedLogger:
    global _enhanced_logger

    if _enhanced_logger:
        return _enhanced_logger

    logger = logging.getLogger(name)
    return EnhancedLogger(logger)


def _display_width(s: str) -> int:
    w = 0
    for ch in s:
        ea = unicodedata.east_asian_width(ch)
        if ea in ("F", "W"):
            w += 2
        else:
            w += 1
    return w


def _pad_label(label: str, target_width: int) -> str:
    pad = max(0, target_width - _display_width(label))
    return label + (" " * pad)


def _startup_tty() -> bool:
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


async def _animate_bar_fill(bar_w: int) -> None:
    c = LogColors
    if not _startup_tty():
        print(f"  {c.CYAN}{'━' * bar_w}{c.RESET}")
        return
    fill = "━"
    ghost = "╌"
    for step in range(bar_w + 1):
        left = f"{c.CYAN}{c.BRIGHT}{fill * step}{c.RESET}"
        mid = f"{c.DIM}{ghost * (bar_w - step)}{c.RESET}" if step < bar_w else ""
        sys.stdout.write(f"\r  {left}{mid} ")
        sys.stdout.flush()
        await asyncio.sleep(0.018)
    sys.stdout.write(f"\r  {c.CYAN}{fill * bar_w}{c.RESET}\n")
    sys.stdout.flush()


async def _reveal_brand_title(text: str, scheme: list[str]) -> None:
    if not _startup_tty():
        print(f"  {create_gradient_text(text, scheme)}")
        return
    for i in range(1, len(text) + 1):
        frag = create_gradient_text(text[:i], scheme)
        pad = " " * max(0, len(text) - i)
        sys.stdout.write(f"\r  {frag}{pad} ")
        sys.stdout.flush()
        await asyncio.sleep(0.055)
    sys.stdout.write("\n")
    sys.stdout.flush()


async def _print_service_pulse(name: str, ok: bool, *, label_col: int) -> None:
    c = LogColors
    spin_a = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
    spin_b = ("◇", "◈", "◆", "◈")
    prefix = "     "
    tw = max(48, shutil.get_terminal_size((80, 24)).columns)
    pad_clear = " " * min(tw, 120)
    lab = _pad_label(name, label_col)
    bar_w = 14
    n_frames = 22
    for i in range(n_frames):
        fr = spin_a[i % len(spin_a)]
        fr2 = spin_b[i % len(spin_b)]
        filled = min(bar_w, int((i + 1) * bar_w / n_frames) + (1 if i % 3 == 0 else 0))
        bar = f"{c.CYAN}{'█' * filled}{c.DIM}{'░' * (bar_w - filled)}{c.RESET}"
        sys.stdout.write(
            f"\r{prefix}{pad_clear}\r{prefix}{c.DIM}{lab}{c.RESET} "
            f"{c.MAGENTA}{fr}{c.RESET}{c.DIM}{fr2}{c.RESET} {bar} "
            f"{c.DIM}checking{c.RESET}"
        )
        sys.stdout.flush()
        await asyncio.sleep(0.04)
    tag = f"{c.GREEN}{c.BRIGHT}● READY{c.RESET}" if ok else f"{c.YELLOW}○ standby{c.RESET}"
    sys.stdout.write(f"\r{prefix}{pad_clear}\r{prefix}{c.DIM}{lab}{c.RESET}  {tag}\n")
    sys.stdout.flush()


def _startup_wrap_width() -> int:
    try:
        cols = shutil.get_terminal_size((80, 24)).columns
    except Exception:
        cols = 80
    return max(36, min(72, cols - 4))


async def print_startup_report(report: dict[str, Any]) -> None:
    c = LogColors
    margin = "  "
    wrap_w = _startup_wrap_width()

    def kv(label: str, value: str) -> None:
        raw = str(value) if value is not None else "—"
        lines = textwrap.wrap(raw, width=wrap_w) or [raw]
        print(f"{margin}{c.DIM}{label}{c.RESET} {lines[0]}")
        for extra in lines[1:]:
            print(f"{margin}  {extra}")

    def section(title: str) -> None:
        print(f"\n{margin}{c.MAGENTA}◆{c.RESET} {c.BRIGHT}{title}{c.RESET}")

    title = str(report.get("title", "运行快照"))
    ms = report.get("startup_ms", "--")
    started = report.get("started_at", "--")
    ver = str(report.get("version", "")).strip()

    scheme = COLOR_SCHEMES.get("purple", COLOR_SCHEMES["default"])
    print()
    await _reveal_brand_title("LY-NEXT", scheme)
    meta_parts: list[str] = [title]
    if ver:
        meta_parts.append(f"v{ver}")
    meta_parts.append(f"{ms} ms")
    meta_parts.append(str(started))
    print(f"{margin}{' · '.join(meta_parts)}")
    await _animate_bar_fill(min(48, wrap_w + 4))

    section("启动统计")
    kv("总耗时", f"{ms} ms")
    kv("启动时间", str(started))

    section("入口与文档")
    kv("HTTP", report.get("server_url", "—"))
    kv("OpenAPI", report.get("docs_url", "—"))
    kv("工作台", report.get("workbench_url", "—"))
    kv("登录页", report.get("workbench_login_url", "—"))

    ws = report.get("ws") or {}
    section("WebSocket")
    kv("基址", ws.get("url", "—"))
    kv("路径摘要", ws.get("paths", "—"))
    if ws.get("service_line"):
        kv("通道", str(ws["service_line"]))

    perf = report.get("perf") or {}
    section("本进程环境")
    kv("内存 RSS", perf.get("mem", "—"))
    kv("逻辑 CPU", perf.get("cpu", "—"))
    kv("平台", perf.get("platform", "—"))
    kv("Python", perf.get("python", "—"))

    api = report.get("api") or {}
    section("路由规模")
    kv("已加载 API 模块", api.get("modules", "—"))
    kv("HTTP 路由数", api.get("http_routes", "—"))
    kv("WS 路由数", api.get("ws_routes", "—"))

    auth = report.get("auth") or {}
    section("鉴权与白名单")
    api_key_raw = str(auth.get("api_key") or "").strip()
    kv("API 密钥", api_key_raw if api_key_raw else "—")
    kv("请求头", str(auth.get("header", "X-API-Key")))
    wl = auth.get("whitelist") or []
    kv("白名单条数", str(len(wl)))
    for p in wl:
        path = str(p)
        print(f"{margin}  {c.DIM}-{c.RESET} {path}")

    services = report.get("services") or {}
    if services:
        section("外部依赖")
        for name, ok in services.items():
            tag = f"{c.GREEN}{c.BRIGHT}● READY{c.RESET}" if ok else f"{c.YELLOW}○ standby{c.RESET}"
            print(f"{margin}{c.DIM}{name}{c.RESET} {tag}")

    for ln in textwrap.wrap("按 Ctrl+C 可停止服务。", width=wrap_w):
        print(f"{margin}{c.DIM}{ln}{c.RESET}")
    print()
