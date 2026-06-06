from __future__ import annotations

import json
from typing import Any

_IMAGE_TOOLS = frozenset({"generate_image", "search_images"})

_IMAGE_EMBED_HINT = (
    "\n\n[系统提示：如果工具返回了图片URL，请用 [image:URL] 格式嵌入到你的回复文字中。"
    '例如："我画了一只猫 [image:https://xxx.png]，你喜欢吗？"'
    "可以同时包含多张图片。]"
)


def is_image_tool(name: str) -> bool:
    return (name or "").strip() in _IMAGE_TOOLS


def tool_result_json(success: bool, **fields: Any) -> str:
    body: dict[str, Any] = {"status": "ok" if success else "error", **fields}
    if not success and "message" not in body:
        body["message"] = "unknown error"
    return json.dumps(body, ensure_ascii=False)


def parse_tool_json(result: Any) -> dict[str, Any] | None:
    if isinstance(result, dict):
        inner = result.get("result")
        if isinstance(inner, str):
            try:
                return json.loads(inner)
            except json.JSONDecodeError:
                return None
        if isinstance(inner, dict):
            return inner
        if "status" in result:
            return result
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return None
    return None


def append_image_embed_hint(formatted: str, tool_name: str) -> str:
    if not is_image_tool(tool_name):
        return formatted
    if _IMAGE_EMBED_HINT.strip() in formatted:
        return formatted
    return formatted + _IMAGE_EMBED_HINT
