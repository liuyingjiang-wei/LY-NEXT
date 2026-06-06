from ly_next.agent.deps import create_agent_deps
from ly_next.agent.image_reply import begin_agent_run, ensure_mixed_reply, finalize_agent_reply
from ly_next.agent.tool_filter import get_filtered_tools_for_deps
from ly_next.tools import get_tool_registry


def test_get_filtered_tools_cached_on_deps():
    deps = create_agent_deps(tools=get_tool_registry())
    begin_agent_run(deps)
    first = get_filtered_tools_for_deps(deps)
    second = get_filtered_tools_for_deps(deps)
    assert first is second


async def test_ensure_mixed_reply_skips_duplicate_finalize():
    deps = create_agent_deps()
    begin_agent_run(deps)
    await finalize_agent_reply(deps, "hello")
    assert deps.last_mixed_message is not None
    mixed = await ensure_mixed_reply(deps, "hello")
    assert mixed is deps.last_mixed_message
