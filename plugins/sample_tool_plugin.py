from ly_next.tools.base import tool


@tool(name="sample_echo", description="Sample tool for directory loader tests", category="general")
async def sample_echo(text: str = "hi") -> str:
    return text


tools = [sample_echo]
