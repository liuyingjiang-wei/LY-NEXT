import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ly_next import __version__
from ly_next.core.logger import get_logger

logger = get_logger(__name__)


class MCPError(Exception):
    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)


@dataclass
class MCPResource:
    uri: str
    name: str
    description: str = ""
    mime_type: str = "text/plain"

    def to_dict(self) -> dict:
        return {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
            "mimeType": self.mime_type,
        }


@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: dict = field(default_factory=dict)
    handler: Callable | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


@dataclass
class MCPPrompt:
    name: str
    description: str
    arguments: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description, "arguments": self.arguments}


class MCPProtocol:
    VERSION = "2024-11-05"

    class Methods:
        INITIALIZE = "initialize"
        SHUTDOWN = "shutdown"
        TOOLS_LIST = "tools/list"
        TOOLS_CALL = "tools/call"
        RESOURCES_LIST = "resources/list"
        RESOURCES_READ = "resources/read"
        PROMPTS_LIST = "prompts/list"
        PROMPTS_GET = "prompts/get"

    def __init__(self):
        self._tools: dict[str, MCPTool] = {}
        self._resources: dict[str, MCPResource] = {}
        self._prompts: dict[str, MCPPrompt] = {}
        self._initialized = False

    def register_tool(self, tool: MCPTool) -> None:
        self._tools[tool.name] = tool

    def register_resource(self, resource: MCPResource) -> None:
        self._resources[resource.uri] = resource

    def register_prompt(self, prompt: MCPPrompt) -> None:
        self._prompts[prompt.name] = prompt

    async def handle_request(self, method: str, params: dict = None) -> dict:
        params = params or {}
        handlers = {
            self.Methods.INITIALIZE: self._handle_initialize,
            self.Methods.SHUTDOWN: self._handle_shutdown,
            self.Methods.TOOLS_LIST: self._handle_tools_list,
            self.Methods.TOOLS_CALL: self._handle_tools_call,
            self.Methods.RESOURCES_LIST: self._handle_resources_list,
            self.Methods.RESOURCES_READ: self._handle_resources_read,
            self.Methods.PROMPTS_LIST: self._handle_prompts_list,
            self.Methods.PROMPTS_GET: self._handle_prompts_get,
        }
        handler = handlers.get(method)
        if not handler:
            raise MCPError(-32601, f"Method not found: {method}")
        return await handler(params)

    async def _handle_initialize(self, params: dict) -> dict:
        self._initialized = True
        return {
            "protocolVersion": self.VERSION,
            "capabilities": {
                "tools": {"listChanged": True},
                "resources": {"subscribe": True, "listChanged": True},
                "prompts": {"listChanged": True},
            },
            "serverInfo": {"name": "ly-next", "version": __version__},
        }

    async def _handle_shutdown(self, params: dict) -> dict:
        self._initialized = False
        return {"success": True}

    async def _handle_tools_list(self, params: dict) -> dict:
        return {"tools": [t.to_dict() for t in self._tools.values()]}

    async def _handle_tools_call(self, params: dict) -> dict:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not name:
            raise MCPError(-32602, "Missing tool name")
        tool = self._tools.get(name)
        if not tool:
            raise MCPError(-32602, f"Tool not found: {name}")
        if not tool.handler:
            raise MCPError(-32603, f"Tool handler not implemented: {name}")
        try:
            result = tool.handler(**arguments)
            if hasattr(result, "__await__"):
                result = await result
            content = [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False)
                    if isinstance(result, dict)
                    else str(result),
                }
            ]
            return {"content": content, "isError": False}
        except Exception as e:
            logger.error(f"Tool {name} failed: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    async def _handle_resources_list(self, params: dict) -> dict:
        return {"resources": [r.to_dict() for r in self._resources.values()]}

    async def _handle_resources_read(self, params: dict) -> dict:
        uri = params.get("uri")
        if not uri:
            raise MCPError(-32602, "Missing resource URI")
        resource = self._resources.get(uri)
        if not resource:
            raise MCPError(-32602, f"Resource not found: {uri}")
        return {"contents": [{"uri": uri, "mimeType": resource.mime_type, "text": ""}]}

    async def _handle_prompts_list(self, params: dict) -> dict:
        return {"prompts": [p.to_dict() for p in self._prompts.values()]}

    async def _handle_prompts_get(self, params: dict) -> dict:
        name = params.get("name")
        if not name:
            raise MCPError(-32602, "Missing prompt name")
        prompt = self._prompts.get(name)
        if not prompt:
            raise MCPError(-32602, f"Prompt not found: {name}")
        return {
            "messages": [{"role": "user", "content": {"type": "text", "text": f"Prompt: {name}"}}]
        }


class MCPServer:
    def __init__(self):
        self.protocol = MCPProtocol()
        self._routes: list[dict] = []

    def tool(self, name: str, description: str = "", input_schema: dict = None):
        def decorator(func):
            tool = MCPTool(
                name=name,
                description=description or func.__doc__ or "",
                input_schema=input_schema or self._infer_schema(func),
                handler=func,
            )
            self.protocol.register_tool(tool)
            return func

        return decorator

    def resource(self, uri: str, name: str, description: str = "", mime_type: str = "text/plain"):
        def decorator(func):
            self.protocol.register_resource(
                MCPResource(uri=uri, name=name, description=description, mime_type=mime_type)
            )
            return func

        return decorator

    def prompt(self, name: str, description: str = "", arguments: list[dict] = None):
        def decorator(func):
            self.protocol.register_prompt(
                MCPPrompt(name=name, description=description, arguments=arguments or [])
            )
            return func

        return decorator

    def _infer_schema(self, func: Callable) -> dict:
        import inspect

        sig = inspect.signature(func)
        properties = {}
        required = []
        type_map = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object",
        }
        for name, param in sig.parameters.items():
            if name == "self":
                continue
            properties[name] = {"type": type_map.get(param.annotation, "string")}
            if param.default == inspect.Parameter.empty:
                required.append(name)
        return {"type": "object", "properties": properties, "required": required}

    async def handle_message(self, method: str, params: dict = None) -> dict:
        try:
            return await self.protocol.handle_request(method, params)
        except MCPError as e:
            return {"error": {"code": e.code, "message": e.message, "data": e.data}}

    @property
    def tools(self) -> list[MCPTool]:
        return list(self.protocol._tools.values())

    @property
    def resources(self) -> list[MCPResource]:
        return list(self.protocol._resources.values())

    @property
    def prompts(self) -> list[MCPPrompt]:
        return list(self.protocol._prompts.values())


mcp_server = MCPServer()
