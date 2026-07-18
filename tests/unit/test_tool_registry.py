import pytest
import pytest_asyncio

from app.core.tool_registry import ToolDefinition, ToolRegistry, ToolNotFoundError


async def _ok_fn(**kw):
    return {"result": "ok"}


async def _add_fn(a, b):
    return {"sum": a + b}


async def _echo_fn(text):
    return {"echo": text}


async def _empty_fn(**kw):
    return {}


@pytest_asyncio.fixture
async def registry():
    return ToolRegistry()


@pytest.mark.asyncio
async def test_register_and_list(registry):
    tool = ToolDefinition(
        name="test_tool",
        description="A test tool",
        parameters={"type": "object", "properties": {}},
        fn=_ok_fn,
    )
    await registry.register(tool)
    tools = await registry.list_all()
    assert len(tools) == 1
    assert tools[0].name == "test_tool"


@pytest.mark.asyncio
async def test_unregister(registry):
    tool = ToolDefinition(
        name="temp", description="Temporary", parameters={}, fn=_empty_fn,
    )
    await registry.register(tool)
    ok = await registry.unregister("temp")
    assert ok is True
    tools = await registry.list_all()
    assert len(tools) == 0


@pytest.mark.asyncio
async def test_unregister_nonexistent(registry):
    ok = await registry.unregister("nonexistent")
    assert ok is False


@pytest.mark.asyncio
async def test_execute(registry):
    tool = ToolDefinition(
        name="add", description="Adds two numbers", parameters={}, fn=_add_fn,
    )
    await registry.register(tool)
    result = await registry.execute("add", {"a": 1, "b": 2})
    assert result == {"sum": 3}


@pytest.mark.asyncio
async def test_execute_not_found(registry):
    with pytest.raises(ToolNotFoundError):
        await registry.execute("nonexistent", {})


@pytest.mark.asyncio
async def test_get_openai_schema(registry):
    tool = ToolDefinition(
        name="echo",
        description="Echo back input",
        parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        fn=_echo_fn,
    )
    await registry.register(tool)
    schema = await registry.get_all_as_openai_schema()
    assert len(schema) == 1
    assert schema[0]["type"] == "function"
    assert schema[0]["function"]["name"] == "echo"
