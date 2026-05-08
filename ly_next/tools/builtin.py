import json
import math
import re
from datetime import datetime

from ly_next.tools.base import ToolResult, tool
from ly_next.tools.http_fetch import http_fetch
from ly_next.tools.web_search import web_scrape_tool, web_search_tool


@tool(
    name="calculator",
    description="Perform mathematical calculations.",
    category="safe",
    parameters={
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Mathematical expression (e.g., '2 + 2', 'sqrt(16)')",
            }
        },
        "required": ["expression"],
    },
)
async def calculator(expression: str) -> ToolResult:
    try:
        allowed_names = {
            "abs": abs,
            "round": round,
            "min": min,
            "max": max,
            "sum": sum,
            "pow": pow,
            "sqrt": math.sqrt,
            "sin": math.sin,
            "cos": math.cos,
            "tan": math.tan,
            "asin": math.asin,
            "acos": math.acos,
            "atan": math.atan,
            "log": math.log,
            "log10": math.log10,
            "log2": math.log2,
            "exp": math.exp,
            "pi": math.pi,
            "e": math.e,
            "floor": math.floor,
            "ceil": math.ceil,
        }

        dangerous = ["import", "eval", "exec", "compile", "open", "file", "__"]
        for d in dangerous:
            if d in expression:
                return ToolResult(success=False, error=f"Forbidden: {d}")

        result = eval(expression, {"__builtins__": {}}, allowed_names)

        return ToolResult(
            success=True,
            result={
                "expression": expression,
                "result": float(result) if isinstance(result, (int, float)) else str(result),
            },
        )
    except Exception as e:
        return ToolResult(success=False, error=f"Calculation error: {str(e)}")


@tool(
    name="format_json",
    description="Format and validate JSON data.",
    category="safe",
    parameters={
        "type": "object",
        "properties": {
            "data": {"type": "string", "description": "JSON string to format"},
            "indent": {"type": "integer", "description": "Indentation level", "default": 2},
        },
        "required": ["data"],
    },
)
async def format_json(data: str, indent: int = 2) -> ToolResult:
    try:
        parsed = json.loads(data)
        formatted = json.dumps(parsed, ensure_ascii=False, indent=indent)
        return ToolResult(success=True, result=formatted)
    except json.JSONDecodeError as e:
        return ToolResult(success=False, error=f"Invalid JSON: {str(e)}")


@tool(
    name="text_process",
    description="Process and transform text.",
    category="general",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "operation": {
                "type": "string",
                "enum": [
                    "upper",
                    "lower",
                    "title",
                    "strip",
                    "word_count",
                    "char_count",
                    "reverse",
                    "length",
                ],
            },
        },
        "required": ["text", "operation"],
    },
)
async def text_process(text: str, operation: str) -> ToolResult:
    operations = {
        "upper": text.upper,
        "lower": text.lower,
        "title": str.title,
        "strip": str.strip,
        "word_count": lambda t: len(t.split()),
        "char_count": lambda t: len(t),
        "reverse": lambda t: t[::-1],
        "length": lambda t: len(t),
    }

    if operation not in operations:
        return ToolResult(success=False, error=f"Unknown operation: {operation}")

    try:
        result = operations[operation](text)
        return ToolResult(
            success=True, result={"operation": operation, "input": text, "output": result}
        )
    except Exception as e:
        return ToolResult(success=False, error=str(e))


@tool(
    name="regex_extract",
    description="Extract text using regex patterns.",
    category="general",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "pattern": {"type": "string", "description": "Regex pattern"},
            "group": {"type": "integer", "description": "Capture group to extract", "default": 0},
        },
        "required": ["text", "pattern"],
    },
)
async def regex_extract(text: str, pattern: str, group: int = 0) -> ToolResult:
    try:
        regex = re.compile(pattern)
        matches = regex.findall(text)

        if not matches:
            return ToolResult(success=True, result={"matches": [], "count": 0})

        extracted = [m[group] if group < len(m) else m for m in matches]

        return ToolResult(success=True, result={"matches": extracted, "count": len(extracted)})
    except re.error as e:
        return ToolResult(success=False, error=f"Regex error: {str(e)}")


@tool(
    name="get_current_time",
    description="Get current date and time.",
    category="general",
    parameters={
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "description": "Date format (strftime)",
                "default": "%Y-%m-%d %H:%M:%S",
            },
            "timezone": {"type": "string", "description": "Timezone", "default": "local"},
        },
    },
)
async def get_current_time(
    format: str = "%Y-%m-%d %H:%M:%S", timezone: str = "local"
) -> ToolResult:
    try:
        if timezone == "local":
            now = datetime.now()
        else:
            import zoneinfo

            tz = zoneinfo.ZoneInfo(timezone)
            now = datetime.now(tz)

        formatted = now.strftime(format)

        return ToolResult(
            success=True,
            result={
                "datetime": formatted,
                "iso": now.isoformat(),
                "timestamp": now.timestamp(),
                "timezone": str(now.tzinfo) if now.tzinfo else "naive",
            },
        )
    except Exception as e:
        return ToolResult(success=False, error=str(e))


@tool(
    name="url_parse",
    description="Parse and extract components from a URL.",
    category="general",
    parameters={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
)
async def url_parse(url: str) -> ToolResult:
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)

        return ToolResult(
            success=True,
            result={
                "scheme": parsed.scheme,
                "netloc": parsed.netloc,
                "hostname": parsed.hostname,
                "port": parsed.port,
                "path": parsed.path,
                "query": parsed.query,
            },
        )
    except Exception as e:
        return ToolResult(success=False, error=str(e))


BUILTIN_TOOLS = [
    calculator,
    format_json,
    text_process,
    regex_extract,
    get_current_time,
    url_parse,
    http_fetch,
    web_search_tool,
    web_scrape_tool,
]
