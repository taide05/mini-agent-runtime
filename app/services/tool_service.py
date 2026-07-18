from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from app.core.tool_registry import ToolDefinition, ToolRegistry
from app.tools.builtin import BUILTIN_TOOLS

_global_registry: ToolRegistry | None = None


async def get_tool_registry() -> ToolRegistry:
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
        for tool_data in BUILTIN_TOOLS:
            await _global_registry.register(ToolDefinition(
                name=tool_data["name"],
                description=tool_data["description"],
                parameters=tool_data["parameters"],
                fn=tool_data["fn"],
                source="builtin",
            ))
    return _global_registry
