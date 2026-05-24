from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.tools.builtins_core import (
    calculator,
    format_json,
    get_current_time,
    regex_extract,
    text_process,
    url_parse,
)
from ly_next.tools.http_fetch import http_fetch
from ly_next.tools.memory_note import remember_fact
from ly_next.tools.registry import ToolRegistry
from ly_next.tools.web_fetch import web_fetch_tool
from ly_next.tools.web_search import web_scrape_tool, web_search_tool

logger = get_logger(__name__)

BUILTIN_TOOLS_BY_NAME: dict[str, object] = {
    "calculator": calculator,
    "format_json": format_json,
    "text_process": text_process,
    "regex_extract": regex_extract,
    "get_current_time": get_current_time,
    "url_parse": url_parse,
    "http_fetch": http_fetch,
    "web_fetch": web_fetch_tool,
    "remember_fact": remember_fact,
    "web_search": web_search_tool,
    "web_scrape": web_scrape_tool,
}

BUILTIN_TOOLS = [BUILTIN_TOOLS_BY_NAME[k] for k in sorted(BUILTIN_TOOLS_BY_NAME)]


def register_builtin_tools(registry: ToolRegistry) -> int:
    raw = config.get("tools.built_in")
    if raw is None:
        names = sorted(BUILTIN_TOOLS_BY_NAME)
    elif isinstance(raw, list):
        if not raw:
            logger.info("tools.built_in is empty; skipping built-in tool registration")
            return 0
        names = [str(x).strip() for x in raw if str(x).strip()]
    else:
        logger.warning(
            "tools.built_in must be a list or null; got %s, registering full built-in set",
            type(raw).__name__,
        )
        names = sorted(BUILTIN_TOOLS_BY_NAME)

    n = 0
    for name in names:
        tool_obj = BUILTIN_TOOLS_BY_NAME.get(name)
        if tool_obj is None:
            logger.warning("Unknown tools.built_in name: %s (ignored)", name)
            continue
        try:
            registry.register(tool_obj)
            n += 1
        except Exception as e:
            logger.warning("Failed to register built-in tool %s: %s", name, e)
    return n
