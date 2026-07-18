import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as DBSession

from app.core.event_bus import get_event_bus
from app.database import get_db
from app.schemas import AgentRunRequest, AgentRunResponse, BranchRequest, NodeResponse
from app.services.agent_service import execute_agent_run
from app.services.session_service import (
    create_node,
    get_node,
    get_node_children,
    get_session,
)

router = APIRouter(tags=["agent"])


@router.post("/sessions/{session_id}/run", response_model=AgentRunResponse)
async def api_run_agent(session_id: str, body: AgentRunRequest, db: DBSession = Depends(get_db)):
    session = get_session(db, session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    result = await execute_agent_run(
        db, session_id, body.content, parent_id=str(body.parent_id) if body.parent_id else None
    )
    return AgentRunResponse(**result)


@router.get("/sessions/{session_id}/stream")
async def api_stream_events(session_id: str):
    event_bus = get_event_bus()
    queue: asyncio.Queue = asyncio.Queue()
    event_bus.subscribe(session_id, queue)

    async def generate():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    data = json.dumps(event, ensure_ascii=False)
                    yield f"event: {event['type']}\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            event_bus.unsubscribe(session_id, queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/sessions/{session_id}/branch", response_model=NodeResponse, status_code=201)
def api_branch(session_id: str, body: BranchRequest, db: DBSession = Depends(get_db)):
    session = get_session(db, session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    parent = get_node(db, str(body.parent_node_id))
    if not parent or str(parent.session_id) != session_id:
        raise HTTPException(404, "Parent node not found in this session")

    node = create_node(
        db, session_id, role=body.role, content=body.content, parent_id=str(body.parent_node_id), status="completed"
    )
    children = get_node_children(db, str(node.id))
    return NodeResponse(
        id=node.id,
        session_id=node.session_id,
        parent_id=node.parent_id,
        branch_depth=node.branch_depth,
        role=node.role,
        content=node.content,
        status=node.status,
        created_at=node.created_at,
        completed_at=node.completed_at,
        children_ids=[c.id for c in children],
    )
