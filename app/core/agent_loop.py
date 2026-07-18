from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from app.core.agent_config import AgentConfig
from app.core.event_bus import EventBus, get_event_bus
from app.core.event_types import EventType, StopReason
from app.core.llm_client import LLMClient, LLMError
from app.core.tool_registry import ToolRegistry, ToolExecutionError, ToolNotFoundError

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful AI assistant with access to tools. "
    "Use tools when you need to look up information or perform calculations. "
    "After using tools, synthesize the results into a clear answer. "
    "If a tool returns an error, try a different approach or explain the issue to the user."
)


@dataclass
class LoopState:
    session_id: str
    node_id: str
    messages: list[dict]
    iteration: int = 0
    should_stop: bool = False
    final_answer: str | None = None
    error: str | None = None


def _build_tool_call_message(tool_calls: list[dict], content: str | None) -> dict:
    openai_tool_calls = []
    for tc in tool_calls:
        openai_tool_calls.append({
            "id": tc["id"],
            "type": "function",
            "function": {
                "name": tc["name"],
                "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
            },
        })
    msg: dict = {"role": "assistant", "content": content, "tool_calls": openai_tool_calls}
    return msg


def _build_tool_result_message(tool_call_id: str, result_str: str) -> dict:
    return {"role": "tool", "tool_call_id": tool_call_id, "content": result_str}


async def run_agent_loop(
    messages: list[dict],
    llm: LLMClient,
    tools: ToolRegistry,
    config: AgentConfig,
    session_id: str = "",
    node_id: str = "",
    event_bus: EventBus | None = None,
) -> LoopState:
    event_bus = event_bus or get_event_bus()
    tools_schema = await tools.get_all_as_openai_schema()
    state = LoopState(
        session_id=session_id,
        node_id=node_id,
        messages=list(messages),
    )

    for iteration in range(1, config.max_iterations + 1):
        state.iteration = iteration

        try:
            response = await llm.chat(state.messages, tools_schema)
        except LLMError as e:
            state.error = str(e)
            state.should_stop = True
            await event_bus.emit(node_id, session_id, EventType.ERROR, {
                "message": str(e),
                "iteration": iteration,
            })
            break

        if response.thinking:
            await event_bus.emit(node_id, session_id, EventType.THINKING, {
                "content": response.thinking,
                "iteration": iteration,
            })

        if response.content:
            await event_bus.emit(node_id, session_id, EventType.TEXT, {
                "content": response.content,
                "iteration": iteration,
                "is_final": not bool(response.tool_calls),
            })

        if not response.tool_calls:
            state.final_answer = response.content
            state.should_stop = True
            state.messages.append({"role": "assistant", "content": response.content})
            await event_bus.emit(node_id, session_id, EventType.STATUS, {
                "status": "completed",
                "message": "Agent finished",
                "stop_reason": StopReason.FINISH.value,
                "iterations": iteration,
            })
            break

        assistant_msg = _build_tool_call_message(response.tool_calls, response.content)
        state.messages.append(assistant_msg)

        for tc in response.tool_calls:
            tool_call_id = tc["id"]
            tool_name = tc["name"]
            arguments = tc["arguments"]

            await event_bus.emit(node_id, session_id, EventType.TOOL_CALL, {
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "arguments": arguments,
                "iteration": iteration,
            })

            start_time = time.monotonic()
            try:
                result = await tools.execute(tool_name, arguments)
                duration_ms = int((time.monotonic() - start_time) * 1000)
                await event_bus.emit(node_id, session_id, EventType.TOOL_RESULT, {
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "result": result,
                    "duration_ms": duration_ms,
                    "is_error": False,
                })
                result_str = json.dumps(result, ensure_ascii=False)
            except (ToolExecutionError, ToolNotFoundError) as e:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                result_str = json.dumps({"error": str(e)})
                await event_bus.emit(node_id, session_id, EventType.TOOL_RESULT, {
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "result": {"error": str(e)},
                    "duration_ms": duration_ms,
                    "is_error": True,
                })

            state.messages.append(_build_tool_result_message(tool_call_id, result_str))

    else:
        state.should_stop = True
        await event_bus.emit(node_id, session_id, EventType.STATUS, {
            "status": "completed",
            "message": f"Reached max iterations ({config.max_iterations})",
            "stop_reason": StopReason.MAX_ITERATIONS.value,
            "iterations": iteration,
        })

        state.messages.append({
            "role": "user",
            "content": "Maximum steps reached. Summarize what you found so far and give your best answer.",
        })
        try:
            fallback = await llm.chat(state.messages)
            state.final_answer = fallback.content
            await event_bus.emit(node_id, session_id, EventType.TEXT, {
                "content": fallback.content,
                "is_final": True,
            })
        except LLMError:
            state.final_answer = "Agent reached iteration limit but could not produce a summary."

    return state
