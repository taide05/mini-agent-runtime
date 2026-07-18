from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from app.core.agent_config import AgentConfig
from app.core.agent_loop import run_agent_loop
from app.core.event_bus import EventBus
from app.core.llm_client import LLMResponse
from app.core.tool_registry import ToolDefinition, ToolRegistry


async def _calc_fn(expr):
    return {"result": eval(expr)}


@pytest_asyncio.fixture
def mock_llm():
    llm = AsyncMock()
    llm.chat.return_value = LLMResponse(content="The answer is 4.", tool_calls=[])
    return llm


@pytest_asyncio.fixture
def mock_llm_with_tool():
    llm = AsyncMock()
    llm.chat.side_effect = [
        LLMResponse(
            content="I'll calculate that.",
            tool_calls=[{"id": "call_1", "name": "calc", "arguments": {"expr": "2+2"}}],
        ),
        LLMResponse(content="The result is 4.", tool_calls=[]),
    ]
    return llm


@pytest_asyncio.fixture
async def registry():
    reg = ToolRegistry()
    tool = ToolDefinition(
        name="calc",
        description="Calculate",
        parameters={"type": "object", "properties": {"expr": {"type": "string"}}, "required": ["expr"]},
        fn=_calc_fn,
    )
    await reg.register(tool)
    return reg


@pytest_asyncio.fixture
def event_bus():
    return EventBus()


@pytest_asyncio.fixture
def config():
    return AgentConfig(max_iterations=5)


@pytest.mark.asyncio
async def test_simple_no_tool_response(mock_llm, registry, event_bus, config):
    messages = [{"role": "user", "content": "What is 2+2?"}]
    state = await run_agent_loop(messages, mock_llm, registry, config, event_bus=event_bus)
    assert state.final_answer == "The answer is 4."
    assert state.iteration == 1
    assert state.should_stop is True


@pytest.mark.asyncio
async def test_single_tool_call(mock_llm_with_tool, registry, event_bus, config):
    messages = [{"role": "user", "content": "Calculate 2+2"}]
    state = await run_agent_loop(messages, mock_llm_with_tool, registry, config, event_bus=event_bus)
    assert state.final_answer == "The result is 4."
    assert state.iteration == 2


@pytest.mark.asyncio
async def test_events_emitted(mock_llm, registry, event_bus, config):
    messages = [{"role": "user", "content": "Hello"}]
    await run_agent_loop(messages, mock_llm, registry, config, "s1", "n1", event_bus)
    events = event_bus.flush_events()
    event_types = [e["event_type"] for e in events]
    assert "text" in event_types or "status" in event_types
