"""agent_loop.py 的测试。运行方式：pytest tests/unit/test_agent_loop.py -v"""

from unittest.mock import AsyncMock

import pytest

from app.core.agent_config import AgentConfig
from app.core.agent_loop import run_agent_loop, LoopState
from app.core.event_bus import EventBus
from app.core.llm_client import LLMResponse, LLMError
from app.core.tool_registry import ToolDefinition, ToolRegistry


# ─── 辅助 ──────────────────────────────────────────────────

async def _calc_fn(expr: str):
    return eval(expr)


async def _search_fn(query: str):
    return {"results": [f"Result for {query}"]}


async def _fail_fn(**kwargs):
    raise RuntimeError("tool error")


@pytest.fixture
def mock_llm():
    """LLM 直接返回文本，不调工具。"""
    llm = AsyncMock()
    llm.chat.return_value = LLMResponse(content="The answer is 4.", tool_calls=[])
    return llm


@pytest.fixture
def mock_llm_with_tool():
    """LLM 第一轮调工具，第二轮返回文本。"""
    llm = AsyncMock()
    llm.chat.side_effect = [
        LLMResponse(
            content="I'll calculate that.",
            tool_calls=[{"id": "call_1", "name": "calc", "arguments": {"expr": "2+2"}}],
        ),
        LLMResponse(content="The result is 4.", tool_calls=[]),
    ]
    return llm


@pytest.fixture
def mock_llm_max_iterations():
    """LLM 一直调工具，超过 max_iterations。"""
    llm = AsyncMock()
    llm.chat.return_value = LLMResponse(
        tool_calls=[{"id": "call_1", "name": "calc", "arguments": {"expr": "1+1"}}],
    )
    return llm


@pytest.fixture
def mock_llm_error():
    """LLM 调用失败。"""
    llm = AsyncMock()
    llm.chat.side_effect = LLMError("API error")
    return llm


@pytest.fixture
async def registry():
    reg = ToolRegistry()
    await reg.register(ToolDefinition(
        name="calc", description="Calculate an expression",
        parameters={"type": "object", "properties": {"expr": {"type": "string"}}, "required": ["expr"]},
        fn=_calc_fn,
    ))
    await reg.register(ToolDefinition(
        name="search", description="Search the web",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        fn=_search_fn,
    ))
    await reg.register(ToolDefinition(
        name="fail_tool", description="Always fails",
        parameters={"type": "object", "properties": {}},
        fn=_fail_fn,
    ))
    return reg


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def config():
    return AgentConfig(max_iterations=5)


# ─── 基本流程 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_simple_no_tool_response(mock_llm, registry, event_bus, config):
    """LLM 不调工具直接返回文本 → 1 轮结束。"""
    messages = [{"role": "user", "content": "What is 2+2?"}]
    state = await run_agent_loop(messages, mock_llm, registry, config, event_bus=event_bus)
    assert state.final_answer == "The answer is 4."
    assert state.iteration == 1
    assert state.should_stop is True


@pytest.mark.asyncio
async def test_single_tool_call(mock_llm_with_tool, registry, event_bus, config):
    """LLM 调一次工具后返回文本 → 2 轮结束。"""
    messages = [{"role": "user", "content": "Calculate 2+2"}]
    state = await run_agent_loop(messages, mock_llm_with_tool, registry, config, event_bus=event_bus)
    assert state.final_answer == "The result is 4."
    assert state.iteration == 2


# ─── 工具异常处理 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_error_reported_to_llm(registry, event_bus, config):
    """工具执行失败 → 错误信息应作为 tool result 返回给 LLM。"""
    llm = AsyncMock()
    llm.chat.side_effect = [
        LLMResponse(
            tool_calls=[{"id": "c1", "name": "fail_tool", "arguments": {}}],
        ),
        LLMResponse(content="The tool failed, let me try differently.", tool_calls=[]),
    ]
    messages = [{"role": "user", "content": "Use fail_tool"}]
    state = await run_agent_loop(messages, llm, registry, config, event_bus=event_bus)
    assert state.final_answer is not None
    # 第二轮调用时 messages 应包含工具错误信息
    second_call_messages = llm.chat.call_args_list[1][0][0]
    tool_results = [m for m in second_call_messages if m["role"] == "tool"]
    assert len(tool_results) == 1


# ─── max_iterations 兜底 ───────────────────────────────────

@pytest.mark.asyncio
async def test_max_iterations_reached(mock_llm_max_iterations, registry, event_bus):
    """达到 max_iterations 后应停止并尝试总结。"""
    config = AgentConfig(max_iterations=3)
    messages = [{"role": "user", "content": "Keep calculating"}]
    state = await run_agent_loop(messages, mock_llm_max_iterations, registry, config, event_bus=event_bus)
    assert state.iteration >= 3
    assert state.should_stop is True


# ─── LLM 调用异常 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_llm_error_stops_loop(mock_llm_error, registry, event_bus, config):
    """LLM 调用失败 → 应直接中断循环并设置 error 字段。"""
    messages = [{"role": "user", "content": "Hello"}]
    state = await run_agent_loop(messages, mock_llm_error, registry, config, event_bus=event_bus)
    assert state.error is not None
    assert state.should_stop is True


# ─── 事件发送 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_events_emitted(mock_llm, registry, event_bus, config):
    """正常流程应发送事件。"""
    messages = [{"role": "user", "content": "Hello"}]
    await run_agent_loop(messages, mock_llm, registry, config, "s1", "n1", event_bus)
    events = event_bus.flush_events()
    event_types = [e["type"] for e in events]
    assert "text" in event_types or "status" in event_types


# ─── 多工具调用 ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_multiple_tool_calls_in_one_turn(registry, event_bus, config):
    """一轮中 LLM 返回多个 tool_calls → 每个都应执行。"""
    llm = AsyncMock()
    llm.chat.side_effect = [
        LLMResponse(
            tool_calls=[
                {"id": "c1", "name": "calc", "arguments": {"expr": "1+1"}},
                {"id": "c2", "name": "search", "arguments": {"query": "test"}},
            ],
        ),
        LLMResponse(content="Done.", tool_calls=[]),
    ]
    messages = [{"role": "user", "content": "Calc and search"}]
    state = await run_agent_loop(messages, llm, registry, config, event_bus=event_bus)
    assert state.final_answer == "Done."


# ─── 消息历史累积 ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_messages_accumulate(mock_llm_with_tool, registry, event_bus, config):
    """每轮对话应追加到 messages 中。"""
    messages = [{"role": "user", "content": "Calc 2+2"}]
    state = await run_agent_loop(messages, mock_llm_with_tool, registry, config, event_bus=event_bus)
    # messages 应包含: user + assistant(with tool_call) + tool_result + assistant(final)
    roles = [m["role"] for m in state.messages]
    assert "tool" in roles
    assert roles.count("assistant") >= 2
