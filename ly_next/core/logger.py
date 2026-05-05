"""Logging: console + rotating file, optional gradient banner helpers."""

import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from ly_next.core.config import config, get_project_root


class LogColors:
    """Terminal color codes."""

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
        """Convert hex color to ANSI escape code."""
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
    "trace": {"symbol": "-", "color": "DIM"},
    "debug": {"symbol": "#", "color": "CYAN"},
    "info": {"symbol": "i", "color": "BLUE"},
    "warn": {"symbol": "!", "color": "YELLOW"},
    "warning": {"symbol": "!", "color": "YELLOW"},
    "error": {"symbol": "x", "color": "RED"},
    "critical": {"symbol": "X", "color": "RED"},
    "success": {"symbol": "+", "color": "GREEN"},
    "mark": {"symbol": "*", "color": "MAGENTA"},
    "tip": {"symbol": "~", "color": "YELLOW"},
    "done": {"symbol": "+", "color": "GREEN"},
}


def create_gradient_text(text: str, colors: list[str] = None) -> str:
    """Create gradient colored text.

    Args:
        text: Text to apply gradient to
        colors: List of hex colors for gradient

    Returns:
        Gradient colored text string
    """
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
        """Get formatted log header with gradient."""
        header_text = "[LY-Next]"
        return create_gradient_text(header_text, self._scheme)

    def _format_message(self, level: str, message: str) -> str:
        style = LOG_STYLES.get(level, LOG_STYLES["info"])
        header = self._get_log_header()
        timestamp = format_timestamp()

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

        return f"{header} {LogColors.DIM}[{timestamp}]{LogColors.RESET} {symbol} {message}"

    def _log(self, level: str, message: str, *args, **kwargs):
        """Internal log method."""
        formatted = self._format_message(level, str(message))
        log_method = getattr(self._logger, level if level != "mark" else "info")
        log_method(formatted, *args, **kwargs)

    # Standard log methods
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

    def critical(self, message: str, *args, **kwargs):
        self._log("critical", message, *args, **kwargs)

    def success(self, message: str, *args, **kwargs):
        """Log success message."""
        formatted = self._format_message("success", f"{LogColors.GREEN}{message}{LogColors.RESET}")
        self._logger.info(formatted, *args, **kwargs)

    def mark(self, message: str, *args, **kwargs):
        """Log marked/highlighted message."""
        formatted = self._format_message("mark", f"{LogColors.MAGENTA}{message}{LogColors.RESET}")
        self._logger.info(formatted, *args, **kwargs)

    def tip(self, message: str, *args, **kwargs):
        """Log tip message."""
        formatted = self._format_message("tip", f"{LogColors.YELLOW}{message}{LogColors.RESET}")
        self._logger.info(formatted, *args, **kwargs)

    # Rich formatting methods
    def title(self, text: str, color: str = "YELLOW"):
        """Print a title with decorative borders."""
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
        """Print a subtitle with decorative borders."""
        header = self._get_log_header()
        timestamp = format_timestamp()
        color_code = getattr(LogColors, color, LogColors.CYAN)

        print(
            f"{header} {LogColors.DIM}[{timestamp}]{LogColors.RESET} {color_code}┌─── {text} ───┐"
        )

    def line(self, char: str = "─", length: int = 40, color: str = "DIM"):
        """Print a separator line."""
        header = self._get_log_header()
        timestamp = format_timestamp()
        color_code = getattr(LogColors, color, LogColors.DIM)

        print(
            f"{header} {LogColors.DIM}[{timestamp}]{LogColors.RESET} {color_code}{char * length}{LogColors.RESET}"
        )

    def box(self, text: str, color: str = "BLUE"):
        """Print text in a box."""
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
        """Print a progress bar."""
        header = self._get_log_header()
        timestamp = format_timestamp()

        percent = min(round((current / total) * 100), 100)
        filled_length = round((current / total) * length)
        bar = "█" * filled_length + "░" * (length - filled_length)

        message = f"{LogColors.CYAN}[{LogColors.GREEN}{bar}{LogColors.CYAN}]{LogColors.YELLOW} {percent}%{LogColors.RESET} {current}/{total}"
        print(f"{header} {LogColors.DIM}[{timestamp}]{LogColors.RESET} {message}")

    def status(self, message: str, status: str, status_color: str = "GREEN"):
        """Print status message with icon."""
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
        }

        icon = status_icons.get(status.lower(), "•")
        color_code = getattr(LogColors, status_color, LogColors.GREEN)

        print(
            f"{header} {LogColors.DIM}[{timestamp}]{LogColors.RESET} {color_code}{icon} [{status.upper()}]{LogColors.RESET} {message}"
        )

    def list(self, items: list[str], title: str = None):
        """Print a list of items."""
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
        """Print a gradient colored line."""
        header = self._get_log_header()
        timestamp = format_timestamp()

        gradient_text = create_gradient_text(char * length, self._scheme)
        print(f"{header} {LogColors.DIM}[{timestamp}]{LogColors.RESET} {gradient_text}")

    def gradient_text(self, text: str) -> str:
        """Return gradient colored text."""
        return create_gradient_text(text, self._scheme)

    # Timer methods
    def time(self, label: str = "default"):
        """Start a timer."""
        self._timers[label] = datetime.now().timestamp()

    def time_end(self, label: str = "default"):
        """End a timer and print duration."""
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


class ColoredFormatter(logging.Formatter):
    """Colored formatter for console output.

    Applies color coding based on log level for better readability.
    """

    # Color scheme for each log level
    LEVEL_COLORS = {
        "DEBUG": LogColors.CYAN,
        "INFO": LogColors.GREEN,
        "WARNING": LogColors.YELLOW,
        "ERROR": LogColors.RED,
        "CRITICAL": LogColors.MAGENTA + LogColors.BRIGHT,
    }

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with colors and unified header.

        Args:
            record: Log record to format

        Returns:
            Formatted log string
        """
        # Apply color to level name
        level_color = self.LEVEL_COLORS.get(record.levelname, LogColors.RESET)
        record.levelname = f"{level_color}{record.levelname}{LogColors.RESET}"

        # Format the message
        return super().format(record)


class UnifiedHeaderFormatter(logging.Formatter):
    CONSOLE_FORMAT = "%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s"
    FILE_FORMAT = "%(asctime)s │ %(levelname)-8s │ %(name)s │ %(filename)s:%(lineno)d │ %(message)s"
    DATE_FORMAT = "%H:%M:%S"  # Short time for console
    FILE_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"  # Full timestamp for files

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.show_module = kwargs.get("show_module", True)
        self.show_filename = kwargs.get("show_filename", True)


# Global enhanced logger instance
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
    """Setup logging with unified header format.

    This function initializes a logger with:
    - Colored console output with gradient support
    - Rotating file logs
    - Consistent header format across all modules
    - Rich formatting methods

    Args:
        name: Logger name (usually module name)
        level: Log level (debug, info, warning, error)
        log_file: Custom log file path
        header: Header prefix for startup banner
        color_scheme: Color scheme for gradient effects

    Returns:
        Configured EnhancedLogger instance
    """
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
        UnifiedHeaderFormatter.CONSOLE_FORMAT, datefmt=UnifiedHeaderFormatter.DATE_FORMAT
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
    file_formatter = logging.Formatter(
        UnifiedHeaderFormatter.FILE_FORMAT, datefmt=UnifiedHeaderFormatter.FILE_DATE_FORMAT
    )
    file_handler.setFormatter(file_formatter)
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
    """Apply ``logging.level`` from YAML to the ``ly_next`` logger (no CLI merge)."""
    logging.getLogger("ly_next").setLevel(_std_level_from_name(config.get("logging.level", "info")))
    _reduce_third_party_log_noise()


def get_logger(name: str) -> EnhancedLogger:
    """Get a logger instance for a module.

    This is the preferred way to get loggers in ly_next modules.
    Each module should use: logger = get_logger(__name__)

    Args:
        name: Module name (typically __name__)

    Returns:
        EnhancedLogger instance for the module
    """
    global _enhanced_logger

    if _enhanced_logger:
        return _enhanced_logger

    logger = logging.getLogger(name)
    return EnhancedLogger(logger)


def print_banner(version: str, host: str, port: int) -> None:
    # Use default color scheme for banner
    scheme = COLOR_SCHEMES["default"]

    # Create gradient lines
    line_length = 60
    gradient_line = create_gradient_text("═" * line_length, scheme)
    gradient_title = create_gradient_text("LY-Next Agent Framework", scheme)

    banner = f"""
{gradient_line}
  {LogColors.BRIGHT}{gradient_title}{LogColors.RESET}
{gradient_line}
  {LogColors.CYAN}Version:{LogColors.RESET}    {LogColors.YELLOW}{version}{LogColors.RESET}
  {LogColors.CYAN}Server:{LogColors.RESET}     {LogColors.GREEN}{host}:{port}{LogColors.RESET}
  {LogColors.CYAN}API Docs:{LogColors.RESET}   {LogColors.CYAN}http://{host}:{port}/docs{LogColors.RESET}
  {LogColors.CYAN}Workbench:{LogColors.RESET} {LogColors.GREEN}http://{host}:{port}/ly/{LogColors.RESET}
{gradient_line}
"""
    print(banner)


def print_service_status(services: dict) -> None:
    """Print service status information.

    Args:
        services: Dictionary of service name -> status info
    """
    print(f"\n{LogColors.CYAN}{'─' * 40}{LogColors.RESET}")

    for name, info in services.items():
        if info.status.value == "running":
            status = f"{LogColors.GREEN}[OK]{LogColors.RESET}"
        elif info.status.value == "stopped":
            status = f"{LogColors.YELLOW}[--]{LogColors.RESET}"
        else:
            status = f"{LogColors.RED}[XX]{LogColors.RESET}"

        print(f"  {name:<12} {status}")

    print(f"{LogColors.CYAN}{'─' * 40}{LogColors.RESET}\n")


def print_xrk_startup_report(report: dict[str, Any]) -> None:
    """Print startup report."""
    line = "=" * 65
    print(f"\n{line}")
    print(f"|  {report.get('title', 'LY-Next 启动完成'):<59}|")
    print(f"{line}\n")

    def section(title: str):
        print(f"-> {title}:")

    def item(label: str, value: str):
        print(f"   - {label}: {value}")

    section("启动统计")
    item("总耗时", f"{report.get('startup_ms', '--')}ms")
    item("启动时间", report.get("started_at", "--"))

    section("服务器信息")
    item("服务器地址", report.get("server_url", "--"))
    item("API Docs", report.get("docs_url", "--"))
    item("工作台", report.get("workbench_url", "--"))
    item("登录页", report.get("workbench_login_url", "--"))

    ws = report.get("ws", {}) or {}
    section("WebSocket服务")
    item("服务地址", ws.get("url", "--"))
    item("连接路径", ws.get("paths", "--"))
    service_line = ws.get("service_line")
    if service_line:
        print(f"   - WebSocket服务: {service_line}")

    perf = report.get("perf", {}) or {}
    section("性能指标")
    item("内存使用", perf.get("mem", "--"))
    item("CPU核心", perf.get("cpu", "--"))
    item("平台", perf.get("platform", "--"))
    item("Python", perf.get("python", "--"))

    api = report.get("api", {}) or {}
    section("API统计")
    item("API模块", api.get("modules", "--"))
    item("HTTP路由", api.get("http_routes", "--"))
    item("WebSocket路由", api.get("ws_routes", "--"))

    auth = report.get("auth", {}) or {}
    section("认证配置")
    item("API密钥", auth.get("api_key", "--"))
    item("请求头", auth.get("header", "X-API-Key"))
    wl = auth.get("whitelist", []) or []
    item("白名单路径", str(len(wl)))
    for p in wl:
        print(f"      - {p}")

    services = report.get("services", {}) or {}
    section("外部服务")
    for name, ok in services.items():
        print(f"   - {name:<10}: {'OK' if ok else '--'}")
    print("")
