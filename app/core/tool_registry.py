"""工具注册中心。

Agent 需要调工具时，通过这个模块完成注册、查询和调用。
"""

from __future__ import annotations
import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol


# ─── 类型定义（已给，直接用）──────────────────────────────


class ToolFunction(Protocol):
    """工具函数的协议：async callable，接收关键字参数。"""

    async def __call__(self, **kwargs: Any) -> Any: ...


@dataclass
class ToolDefinition:

    name: str
    description: str
    parameters: dict[str, Any]
    fn: ToolFunction
    source: str = "builtin"
    registered_at: datetime | None = None


@dataclass
class StructuredToolError:
    """工具执行失败的结构化错误，帮助 LLM 精确理解问题并自纠正。"""
    error_type: str
    message: str
    param_name: str | None = None
    expected: str | None = None
    suggestion: str | None = None


class ToolNotFoundError(Exception):
    """工具未注册时抛出。"""


class ToolExecutionError(Exception):
    """工具执行失败时抛出。"""


# ─── 你要实现的类 ──────────────────────────────────────────


class ToolRegistry:
    """工具注册中心。

    以 name 为 key 存储 ToolDefinition。使用 asyncio.Lock 保证并发安全。

    核心方法（按建议实现顺序）：
    1. register  — 注册新工具
    2. get       — 按名称获取
    3. list_all  — 列出全部
    4. execute   — 调用工具
    5. unregister — 注销工具
    6. get_all_as_openai_schema — 导出为 OpenAI function calling 格式

    使用示例（你的实现应该通过这些场景）：

    >>> registry = ToolRegistry()
    >>> async def add(a: int, b: int): return a + b
    >>> await registry.register(ToolDefinition(
    ...     name="add", description="add two numbers",
    ...     parameters={"type":"object","properties":{"a":{"type":"number"},"b":{"type":"number"}}},
    ...     fn=add,
    ... ))
    >>> await registry.get("add")  # 返回 ToolDefinition
    >>> await registry.execute("add", {"a": 1, "b": 2})  # 返回 3
    >>> await registry.list_all()  # 返回 [ToolDefinition, ...]
    """

    def __init__(self) -> None:
        self._tools:dict[str,ToolDefinition] = {}
        self._lock = asyncio.Lock()

    async def register(self, tool_def: ToolDefinition) -> None:
        async with self._lock:
            if tool_def.name in self._tools:
                raise ValueError(f"工具'{tool_def.name}'已存在")
            tool_def.registered_at = datetime.now(timezone.utc)
            self._tools[tool_def.name] = tool_def

    async def unregister(self, name: str) -> bool:
        async with self._lock:
            if name in self._tools:
                del self._tools[name]
                return True
            return False
    async def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    async def list_all(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    async def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        try:
            tool_def = await self.get(name)
            if tool_def is None:
                raise ToolNotFoundError(f"工具'{name}'不存在")
            return await tool_def.fn(**arguments)
        except ToolNotFoundError:
            raise
        except ToolExecutionError:
            raise
        except Exception as e:
            detail = StructuredToolError(
                error_type="execution_error",
                message=f"工具'{name}'执行时出错: {e}",
                suggestion=f"请检查传给 {name} 的参数是否正确，或尝试换一种方式调用",
            )
            raise ToolExecutionError(json.dumps(detail.__dict__, ensure_ascii=False)) from e

    async def get_all_as_openai_schema(self) -> list[dict[str, Any]]:
        all_tools = await self.list_all()
        result = []
        for t in all_tools:
            result.append({
                "type":"function",
                "function":{
                    "name":t.name,
                    "description":t.description,
                    "parameters":t.parameters
                },
            })
        return result