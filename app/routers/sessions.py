from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from app.database import get_db
from app.schemas import SessionCreate, SessionResponse, SessionTreeResponse
from app.services.session_service import (
    create_session,
    delete_session,
    get_session,
    get_session_tree,
    list_sessions,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse, status_code=201)
def api_create_session(body: SessionCreate, db: DBSession = Depends(get_db)):
    session = create_session(
        db,
        title=body.title,
        system_prompt=body.system_prompt,
        model=body.model,
        metadata=body.metadata,
    )
    return SessionResponse(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        node_count=0,
    )


@router.get("", response_model=list[SessionResponse])
def api_list_sessions(db: DBSession = Depends(get_db)):
    sessions = list_sessions(db)
    return [
        SessionResponse(
            id=s.id,
            title=s.title,
            created_at=s.created_at,
            updated_at=s.updated_at,
            node_count=len(s.nodes),
        )
        for s in sessions
    ]


@router.get("/{session_id}", response_model=SessionResponse)
def api_get_session(session_id: str, db: DBSession = Depends(get_db)):
    session = get_session(db, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return SessionResponse(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        node_count=len(session.nodes),
    )


@router.delete("/{session_id}", status_code=204)
def api_delete_session(session_id: str, db: DBSession = Depends(get_db)):
    ok = delete_session(db, session_id)
    if not ok:
        raise HTTPException(404, "Session not found")


@router.get("/{session_id}/tree", response_model=SessionTreeResponse)
def api_get_tree(session_id: str, db: DBSession = Depends(get_db)):
    session = get_session(db, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return get_session_tree(db, session_id)
