"""Text-to-image tool — OpenAI-compatible /images/generations only."""

from __future__ import annotations

from ly_next.agent.run_context import get_current_thread_id
from ly_next.core.logger import get_logger
from ly_next.tools.base import ToolResult, tool
from ly_next.tools.image_gen_providers import GEN_PROVIDER_ID, generate_openai_compat_image
from ly_next.tools.image_quota import (
    consume_quota,
    daily_limit,
    get_cached_image_url,
    get_remaining_quota,
    release_quota,
    set_cached_image_url,
)
from ly_next.tools.image_stats import record_tool_call
from ly_next.tools.image_tool_helpers import tool_result_json

logger = get_logger(__name__)


def _user_key(explicit: str | None) -> str:
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    tid = get_current_thread_id()
    return tid if tid else "anonymous"


@tool(
    name="generate_image",
    description=(
        "Call when the user wants AI-generated art from a text prompt (画画/生成图片). "
        "Returns image_url on success. Not for finding existing images (search_images)."
    ),
    category="image",
)
async def generate_image(prompt: str, user_key: str = "") -> ToolResult:
    prompt = (prompt or "").strip()
    if not prompt:
        return ToolResult(
            success=False,
            result=tool_result_json(False, message="prompt 不能为空"),
        )

    uk = _user_key(user_key or None)
    remaining = await get_remaining_quota(uk)
    if remaining <= 0:
        await record_tool_call("generate_image", success=False)
        return ToolResult(
            success=False,
            result=tool_result_json(
                False,
                message=f"今日生图次数已用完（每日上限 {daily_limit()}）",
                image_quota_remaining=0,
            ),
        )

    provider = GEN_PROVIDER_ID
    cached = await get_cached_image_url(prompt, provider)
    if cached:
        await record_tool_call("generate_image", success=True)
        return ToolResult(
            success=True,
            result=tool_result_json(
                True,
                image_url=cached,
                cached=True,
                provider=provider,
                image_quota_remaining=remaining,
            ),
        )

    allowed, left = await consume_quota(uk)
    if not allowed:
        await record_tool_call("generate_image", success=False)
        return ToolResult(
            success=False,
            result=tool_result_json(
                False,
                message="今日生图次数已用完",
                image_quota_remaining=0,
            ),
        )

    try:
        image_url = await generate_openai_compat_image(prompt)
        if image_url.startswith("http"):
            await set_cached_image_url(prompt, provider, image_url)
        await record_tool_call("generate_image", success=True)
        return ToolResult(
            success=True,
            result=tool_result_json(
                True,
                image_url=image_url,
                provider=provider,
                image_quota_remaining=left,
            ),
        )
    except Exception as e:
        logger.warning("[generate_image] failed: %s", e)
        await release_quota(uk)
        remaining_after = await get_remaining_quota(uk)
        await record_tool_call("generate_image", success=False)
        return ToolResult(
            success=False,
            result=tool_result_json(
                False,
                message=str(e),
                image_quota_remaining=remaining_after,
            ),
        )
