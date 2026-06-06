from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    scratchpad: str
    steps: int
    decision: dict[str, Any]
    tool_results: list[dict[str, Any]]
    last_tool: str
    last_result: Any
    error: str
    final_response: str
    mixed_message: dict[str, Any] | None
    image_quota_remaining: int
    last_tool_signature: str
    repeat_tool_calls: int
    tool_fail_streak: int


def create_initial_state(messages: list[dict[str, Any]] | None = None) -> AgentState:
    return AgentState(
        messages=messages or [],
        scratchpad="",
        steps=0,
        decision={},
        tool_results=[],
        last_tool="",
        last_result=None,
        error="",
        final_response="",
        mixed_message=None,
        image_quota_remaining=0,
        last_tool_signature="",
        repeat_tool_calls=0,
        tool_fail_streak=0,
    )
