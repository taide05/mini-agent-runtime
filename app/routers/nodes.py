from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from app.database import get_db
from app.schemas import EventResponse, NodeResponse
from app.services.session_service import get_node, get_node_children

router = APIRouter(prefix="/nodes", tags=["nodes"])


@router.get("/{node_id}", response_model=NodeResponse)
def api_get_node(node_id: str, db: DBSession = Depends(get_db)):
    node = get_node(db, node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    children = get_node_children(db, node_id)
    return NodeResponse(
        id=node.id,
        session_id=node.session_id,
        parent_id=node.parent_id,
        branch_depth=node.branch_depth,
        role=node.role,
        content=node.content,
        thinking=node.thinking,
        status=node.status,
        error_message=node.error_message,
        created_at=node.created_at,
        completed_at=node.completed_at,
        children_ids=[c.id for c in children],
    )


@router.get("/{node_id}/events", response_model=list[EventResponse])
def api_get_node_events(node_id: str, db: DBSession = Depends(get_db)):
    node = get_node(db, node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    events = sorted(node.events, key=lambda e: e.seq)
    return [
        EventResponse(
            id=e.id,
            node_id=e.node_id,
            seq=e.seq,
            event_type=e.event_type,
            payload=e.payload_json,
            created_at=e.created_at,
        )
        for e in events
    ]
