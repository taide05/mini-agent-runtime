from __future__ import annotations

from sqlalchemy.orm import Session as DBSession

from app.core.agent_config import AgentConfig
from app.core.agent_loop import run_agent_loop
from app.core.event_bus import get_event_bus
from app.core.llm_client import LLMClient
from app.services.session_service import (
    assemble_messages_from_chain,
    complete_node,
    create_node,
    get_session,
)
from app.services.event_service import persist_events
from app.services.tool_service import get_tool_registry


async def execute_agent_run(
    db: DBSession,
    session_id: str,
    content: str,
    parent_id: str | None = None,
) -> dict:
    session = get_session(db, session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")

    meta = session.metadata_json or {}
    system_prompt = meta.get("system_prompt", "")
    model = meta.get("model", "deepseek-chat")

    messages = assemble_messages_from_chain(db, parent_id, content, system_prompt)

    user_node = create_node(db, session_id, role="user", content=content, parent_id=parent_id, status="completed")
    assistant_node = create_node(
        db, session_id, role="assistant", parent_id=str(user_node.id), status="running"
    )

    if not system_prompt:
        sp = ("You are a helpful AI assistant with access to tools. "
              "Use tools when needed and synthesize results into clear answers.")
    else:
        sp = system_prompt

    config = AgentConfig(system_prompt=sp, model=model)
    llm = LLMClient(model=model)
    tools = await get_tool_registry()
    event_bus = get_event_bus()

    state = await run_agent_loop(
        messages=messages,
        llm=llm,
        tools=tools,
        config=config,
        session_id=str(assistant_node.session_id),
        node_id=str(assistant_node.id),
        event_bus=event_bus,
    )

    final_status = "failed" if state.error else "completed"
    events = event_bus.flush_events()
    persist_events(db, events)
    complete_node(
        db,
        str(assistant_node.id),
        content=state.final_answer,
        status=final_status,
        error_message=state.error,
    )

    return {
        "node_id": str(assistant_node.id),
        "session_id": session_id,
        "status": final_status,
    }
