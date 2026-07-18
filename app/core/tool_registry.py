from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol


class ToolFunction(Protocol):
    async def __call__(self, **kwargs: Any) -> Any: ...


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: ToolFunction
    source: str = "builtin"
    registered_at: datetime | None = None


class ToolNotFoundError(Exception):
    pass


class ToolExecutionError(Exception):
    pass


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._lock = asyncio.Lock()

    async def register(self, tool_def: ToolDefinition) -> None:
        async with self._lock:
            tool_def.registered_at = datetime.now(timezone.utc)
            self._tools[tool_def.name] = tool_def

    async def unregister(self, name: str) -> bool:
        async with self._lock:
            if name in self._tools:
                del self._tools[name]
                return True
            return False

    async def get(self, name: str) -> ToolDefinition | None:
        async with self._lock:
            return self._tools.get(name)

    async def list_all(self) -> list[ToolDefinition]:
        async with self._lock:
            return list(self._tools.values())

    async def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        tool_def = await self.get(name)
        if not tool_def:
            raise ToolNotFoundError(f"Tool '{name}' not registered")
        try:
            result = await tool_def.fn(**arguments)
            return result
        except ToolNotFoundError:
            raise
        except Exception as e:
            raise ToolExecutionError(f"Tool '{name}' failed: {e}") from e

    async def get_all_as_openai_schema(self) -> list[dict]:
        tools = await self.list_all()
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]
