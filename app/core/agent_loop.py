"""ReAct Agent 主循环。

Thought → Action → Observation 循环是 Agent 的心脏。
这个文件是你的第三个实现目标，也是三个文件中最复杂的一个。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from app.core.agent_config import AgentConfig
from app.core.event_bus import EventBus, get_event_bus
from app.core.event_types import EventType, StopReason
from app.core.llm_client import LLMClient, LLMError
from app.core.tool_registry import ToolRegistry, ToolExecutionError, ToolNotFoundError


# ─── 数据结构 ───────────────────────────────────────────


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
        openai_tool_calls.append(
            {
                "id":tc["id"],
                "type":"function",
                "function":{
                    "name":tc["name"],
                    "arguments":json.dumps(tc["arguments"],ensure_ascii=False)
                }
            }
        )
    result_dict_cm = {
        "role":"assistant",
        "content":content,
        "tool_calls":openai_tool_calls
    }
    return result_dict_cm

def _build_tool_result_message(tool_call_id: str, result_str: str) -> dict:
    result_dict_rs = {
        "role":"tool",
        "tool_call_id":tool_call_id,
        "content":result_str
    }
    return result_dict_rs
# ─── 主函数：你要实现的 ────────────────────────────────────


async def run_agent_loop(
    messages: list[dict],
    llm: LLMClient,
    tools: ToolRegistry,
    config: AgentConfig,
    session_id: str = "",
    node_id: str = "",
    event_bus: EventBus | None = None,
) -> LoopState:
    if event_bus is None:
        event_bus = get_event_bus()
    schema = await tools.get_all_as_openai_schema()
    state = LoopState(
        session_id = session_id,
        node_id = node_id,
        messages = list(messages)
    )
    for iteration in range(1,config.max_iterations + 1):
        state.iteration = iteration
        try:
            response = await llm.chat(state.messages,schema)
            if response.thinking:
                await event_bus.emit(node_id,session_id,EventType.THINKING,{"content":response.thinking,"iteration":iteration})
            if response.content:
                await event_bus.emit(node_id,session_id,EventType.TEXT,{"content":response.content,"iteration":iteration,"is_final":not bool(response.tool_calls)})
            if not response.tool_calls:
                state.final_answer = response.content
                state.should_stop = True 
                state.messages.append({"role":"assistant","content":response.content})
                break
            else:
                assistant = _build_tool_call_message(response.tool_calls,response.content)
                state.messages.append(assistant)
                for tc in response.tool_calls:
                    tool_call_id = tc["id"]
                    tool_name = tc["name"]
                    arguments = tc["arguments"]
                    await event_bus.emit(node_id,session_id,EventType.TOOL_CALL,{
                        "tool_call_id":tool_call_id,
                        "tool_name":tool_name,
                        "arguments":arguments,
                        "iteration":iteration,
                    })
                    start_time = time.monotonic()
                    try:
                        result = await tools.execute(tool_name,arguments)
                        result_str = json.dumps(result,ensure_ascii=False)
                        duration_ms = int((time.monotonic() - start_time) * 1000)
                        await event_bus.emit(node_id,session_id,EventType.TOOL_RESULT,{
                            "tool_call_id":tool_call_id,
                            "tool_name":tool_name,
                            "result":result,
                            "duration_ms":duration_ms,
                            "is_error":False,
                        })
                    except (ToolExecutionError,ToolNotFoundError) as e:
                        result_str = str(e)
                        duration_ms = int((time.monotonic() - start_time) * 1000)
                        await event_bus.emit(node_id,session_id,EventType.TOOL_RESULT,{
                            "tool_call_id":tool_call_id,
                            "tool_name":tool_name,
                            "result":{"error": True, "detail": result_str},
                            "duration_ms":duration_ms,
                            "is_error":True,
                        })
                    state.messages.append(_build_tool_result_message(tool_call_id,result_str))
        except LLMError as exc:
            state.error = str(exc)
            state.should_stop = True
            break
    else:
        state.should_stop = True 
        await event_bus.emit(node_id,session_id,EventType.STATUS,{
            "status":"completed",
            "message":f"Reached max iterations({config.max_iterations})",
            "stop_reason":StopReason.MAX_ITERATIONS.value,
            "iterations":config.max_iterations
        })
        state.messages.append({"role":"user","content":"Maximum steps reached. Summarize what you found so far and give your best answer."})
        try:
            fallback = await llm.chat(state.messages)
            state.final_answer = fallback.content
        except LLMError as exc:
            state.final_answer = "Agent reached iteration limit but could not produce a summary."
    return state