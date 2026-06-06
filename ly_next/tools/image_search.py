"""Search images on the web — multi-vendor backends."""

from __future__ import annotations

from ly_next.core.logger import get_logger
from ly_next.tools.base import ToolResult, tool
from ly_next.tools.image_gen_providers import image_cfg
from ly_next.tools.image_search_providers import search_with_provider
from ly_next.tools.image_stats import record_tool_call
from ly_next.tools.image_tool_helpers import tool_result_json

logger = get_logger(__name__)


@tool(
    name="search_images",
    description=(
        "在网络上搜索与关键词相关的图片，返回最多 3 张图片 URL。用户要找图、搜图、发参考图时使用。"
    ),
    category="image",
)
async def search_images(query: str, count: int = 3) -> ToolResult:
    query = (query or "").strip()
    if not query:
        return ToolResult(
            success=False,
            result=tool_result_json(False, message="query 不能为空"),
        )
    n = max(1, min(int(count or 3), 3))
    provider = str(image_cfg().get("search_provider") or "bing").strip().lower()
    try:
        urls = await search_with_provider(query, count=n, provider=provider)
        if not urls:
            await record_tool_call("search_images", success=False)
            return ToolResult(
                success=False,
                result=tool_result_json(False, message="未找到相关图片"),
            )
        await record_tool_call("search_images", success=True)
        return ToolResult(
            success=True,
            result=tool_result_json(True, image_urls=urls, provider=provider),
        )
    except Exception as e:
        logger.warning("[search_images] failed: %s", e)
        await record_tool_call("search_images", success=False)
        return ToolResult(
            success=False,
            result=tool_result_json(False, message=str(e)),
        )
