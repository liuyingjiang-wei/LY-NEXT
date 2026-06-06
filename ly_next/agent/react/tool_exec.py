"""Native OpenAI tool-call execution for ReAct loops."""

from __future__ import annotations

import time
from typing import Any

from ly_next.agent.deps import AgentDeps
from ly_next.agent.react.helpers import run_tool_with_obs
from ly_next.core.logger import get_logger
from ly_next.core.run_telemetry import record_tool_timing

logger = get_logger(__name__)


async def execute_native_tool_call(
    deps: AgentDeps,
    *,
    name: str,
    args: dict[str, Any],
    call_id: str,
    run_tag: str,
    allowed_set: set[str],
) -> dict[str, Any]:
    import json

    t_tool = time.perf_counter()
    if allowed_set and name not in allowed_set:
        result: Any = {"success": False, "error": f"Tool not allowed: {name}"}
        tool_body = str(result.get("error") or "")
    else:
        try:
            result, tool_body = await run_tool_with_obs(
                deps,
                name,
                args,
                call_id=call_id,
                run_tag=run_tag,
            )
        except Exception as e:
            logger.error("[agent.native] tool %s failed: %s", name, e)
            result = {"success": False, "error": str(e)}
            tool_body = str(e)

    ok = not (isinstance(result, dict) and result.get("success") is False)
    record_tool_timing(name, (time.perf_counter() - t_tool) * 1000.0, ok)
    preview = tool_body if len(tool_body) <= 2000 else tool_body[:1999] + "…"
    sig = json.dumps({"name": name, "args": args}, sort_keys=True, ensure_ascii=False)
    return {
        "name": name,
        "args": args,
        "call_id": call_id,
        "tool_body": tool_body,
        "ok": ok,
        "preview": preview,
        "sig": sig,
    }
