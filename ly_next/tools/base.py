"""Base Tool."""

import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolDefinition:
    """Tool definition metadata."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    category: str = "general"

    def to_openai_format(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_langchain_format(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "schema": self.parameters,
        }


@dataclass
class ToolResult:
    """Tool execution result."""

    success: bool
    result: Any = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.success:
            return {"success": True, "result": self.result}
        return {"success": False, "error": self.error or "Unknown error"}


class BaseTool(ABC):
    """Abstract base class for tools."""

    @property
    @abstractmethod
    def definition(self) -> ToolDefinition:
        pass

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        pass

    @property
    def name(self) -> str:
        return self.definition.name

    @property
    def description(self) -> str:
        return self.definition.description

    async def __call__(self, **kwargs) -> ToolResult:
        return await self.execute(**kwargs)


def tool(
    name: str,
    description: str = "",
    parameters: dict[str, Any] | None = None,
    category: str = "general",
):
    """Decorator to create a tool from an async function."""

    def decorator(func):
        async def wrapper(**kwargs) -> ToolResult:
            try:
                sig = inspect.signature(func)
                bound = sig.bind(**kwargs)
                bound.apply_defaults()
                result = await func(**bound.arguments)
                if isinstance(result, ToolResult):
                    return result
                return ToolResult(success=True, result=result)
            except Exception as e:
                return ToolResult(success=False, error=str(e))

        async def execute(**kwargs) -> ToolResult:
            return await wrapper(**kwargs)

        sig = inspect.signature(func)
        params = sig.parameters

        properties = {}
        required = []
        for param_name, param in params.items():
            if param_name == "self":
                continue

            param_type = "string"
            if param.annotation != inspect.Parameter.empty:
                type_map = {
                    str: "string",
                    int: "integer",
                    float: "number",
                    bool: "boolean",
                    list: "array",
                    dict: "object",
                }
                param_type = type_map.get(param.annotation, "string")

            properties[param_name] = {"type": param_type}

            if param.default == inspect.Parameter.empty:
                required.append(param_name)
            else:
                properties[param_name]["default"] = param.default

        tool_params = parameters or {
            "type": "object",
            "properties": properties,
            "required": required,
        }

        wrapper.definition = ToolDefinition(
            name=name,
            description=description or func.__doc__ or "",
            parameters=tool_params,
            category=category,
        )
        wrapper.name = name
        wrapper.description = description
        wrapper.execute = execute

        return wrapper

    return decorator
