"""
Manual smoke test for Mini Agent Runtime.

Requirements: PostgreSQL and Redis running, DEEPSEEK_API_KEY in .env or env var.

Usage: python tests/manual_smoke_test.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.agent_config import AgentConfig
from app.core.agent_loop import run_agent_loop
from app.core.event_bus import EventBus
from app.core.llm_client import LLMClient
from app.services.tool_service import get_tool_registry


async def test_tool_registry():
    print("=== Test 1: Tool Registry ===")
    registry = await get_tool_registry()
    tools = await registry.list_all()
    assert len(tools) >= 3, f"Expected >= 3 builtin tools, got {len(tools)}"
    print(f"  {len(tools)} tools registered: {[t.name for t in tools]}")

    result = await registry.execute("calculator", {"expression": "2+3*4"})
    assert result["result"] == 14, f"Expected 14, got {result}"
    print(f"  calculator(2+3*4) = {result['result']}")

    schema = await registry.get_all_as_openai_schema()
    assert len(schema) >= 3
    print("  OpenAI schema generated OK")

    print("  PASSED")


async def test_agent_loop_no_tools():
    print("\n=== Test 2: Agent Loop (no tools needed) ===")
    llm = LLMClient()
    registry = await get_tool_registry()
    event_bus = EventBus()
    config = AgentConfig(max_iterations=5)

    messages = [
        {"role": "system", "content": "You are a helpful assistant. Answer briefly."},
        {"role": "user", "content": "What is 2+2? Answer in one sentence."},
    ]

    state = await run_agent_loop(messages, llm, registry, config, event_bus=event_bus)
    print(f"  Iterations: {state.iteration}")
    print(f"  Answer: {state.final_answer[:100]}...")
    print(f"  Events: {len(event_bus.flush_events())}")
    assert state.final_answer is not None, "Expected a final answer"
    print("  PASSED")


async def test_agent_loop_with_tool():
    print("\n=== Test 3: Agent Loop (tool use) ===")
    llm = LLMClient()
    registry = await get_tool_registry()
    event_bus = EventBus()
    config = AgentConfig(max_iterations=5)

    messages = [
        {"role": "system", "content": "You are a helpful assistant. Use the calculator tool for math."},
        {"role": "user", "content": "Calculate 15 * 37 + 42"},
    ]

    state = await run_agent_loop(messages, llm, registry, config, "smoke_s", "smoke_n", event_bus)
    print(f"  Iterations: {state.iteration}")
    print(f"  Answer: {state.final_answer[:200]}...")

    events = event_bus.flush_events()
    event_types = [e["event_type"] for e in events]
    print(f"  Event types: {event_types}")
    assert state.final_answer is not None
    assert "tool_call" in event_types, f"Expected tool_call event, got {event_types}"
    print("  PASSED")


async def main():
    print("Mini Agent Runtime — Manual Smoke Test\n")
    try:
        await test_tool_registry()
        await test_agent_loop_no_tools()
        await test_agent_loop_with_tool()
        print("\n=== ALL SMOKE TESTS PASSED ===")
    except Exception as e:
        print(f"\nFAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
