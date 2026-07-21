"""tool_registry.py 的测试。运行方式：pytest tests/unit/test_tool_registry.py -v"""

import asyncio

import pytest

from app.core.tool_registry import (
    ToolDefinition,
    ToolExecutionError,
    ToolNotFoundError,
    ToolRegistry,
)


# ─── 辅助函数 ──────────────────────────────────────────────

async def _echo(**kwargs):
    return kwargs


async def _add(a: int, b: int):
    return a + b


async def _fail(**kwargs):
    raise RuntimeError("tool exploded")


def _make_def(name="test", description="a test tool", parameters=None, fn=None):
    return ToolDefinition(
        name=name,
        description=description,
        parameters=parameters or {"type": "object", "properties": {}},
        fn=fn or _echo,
    )


# ─── register ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_sets_registered_at():
    registry = ToolRegistry()
    tool_def = _make_def()
    await registry.register(tool_def)
    assert tool_def.registered_at is not None


@pytest.mark.asyncio
async def test_register_duplicate_raises_value_error():
    registry = ToolRegistry()
    await registry.register(_make_def(name="dup"))
    with pytest.raises(ValueError):
        await registry.register(_make_def(name="dup"))


# ─── get ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_returns_tool_definition():
    registry = ToolRegistry()
    tool_def = _make_def(name="my_tool")
    await registry.register(tool_def)
    result = await registry.get("my_tool")
    assert result is tool_def


@pytest.mark.asyncio
async def test_get_nonexistent_returns_none():
    registry = ToolRegistry()
    assert await registry.get("does_not_exist") is None


# ─── list_all ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_all_empty_initially():
    registry = ToolRegistry()
    assert await registry.list_all() == []


@pytest.mark.asyncio
async def test_list_all_returns_all_registered():
    registry = ToolRegistry()
    t1 = _make_def(name="t1")
    t2 = _make_def(name="t2")
    await registry.register(t1)
    await registry.register(t2)
    tools = await registry.list_all()
    assert len(tools) == 2
    assert t1 in tools and t2 in tools


# ─── execute ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_calls_tool_and_returns_result():
    registry = ToolRegistry()
    await registry.register(_make_def(name="add", fn=_add))
    assert await registry.execute("add", {"a": 1, "b": 2}) == 3


@pytest.mark.asyncio
async def test_execute_nonexistent_raises_tool_not_found():
    registry = ToolRegistry()
    with pytest.raises(ToolNotFoundError):
        await registry.execute("no_such_tool", {})


@pytest.mark.asyncio
async def test_execute_tool_error_wrapped():
    registry = ToolRegistry()
    await registry.register(_make_def(name="fail", fn=_fail))
    with pytest.raises(ToolExecutionError) as exc_info:
        await registry.execute("fail", {})
    assert "fail" in str(exc_info.value)
    assert "tool exploded" in str(exc_info.value)


# ─── unregister ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unregister_removes_tool():
    registry = ToolRegistry()
    await registry.register(_make_def(name="temp"))
    assert await registry.unregister("temp") is True
    assert await registry.get("temp") is None


@pytest.mark.asyncio
async def test_unregister_nonexistent_returns_false():
    registry = ToolRegistry()
    assert await registry.unregister("no_such") is False


# ─── get_all_as_openai_schema ───────────────────────────────

@pytest.mark.asyncio
async def test_get_all_as_openai_schema_empty():
    registry = ToolRegistry()
    assert await registry.get_all_as_openai_schema() == []


@pytest.mark.asyncio
async def test_get_all_as_openai_schema_format():
    registry = ToolRegistry()
    await registry.register(_make_def(
        name="search",
        description="search the web",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
    ))
    schema = await registry.get_all_as_openai_schema()
    assert len(schema) == 1
    item = schema[0]
    assert item["type"] == "function"
    func = item["function"]
    assert func["name"] == "search"
    assert func["description"] == "search the web"
    assert "parameters" in func
    assert "fn" not in func and "fn" not in item


# ─── 并发安全 ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_registration():
    registry = ToolRegistry()

    async def register_one(i):
        await registry.register(_make_def(name=f"tool_{i}"))

    await asyncio.gather(*[register_one(i) for i in range(20)])
    tools = await registry.list_all()
    assert len(tools) == 20
