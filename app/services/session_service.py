from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session as DBSession

from app.models import Node, Session


def create_session(
    db: DBSession,
    title: str | None = None,
    system_prompt: str | None = None,
    model: str = "deepseek-chat",
    metadata: dict[str, Any] | None = None,
) -> Session:
    meta = metadata or {}
    if system_prompt:
        meta["system_prompt"] = system_prompt
    if model:
        meta["model"] = model

    session = Session(
        id=uuid4(),
        title=title,
        metadata_json=meta,
    )
    db.add(session)
    db.flush()
    return session


def get_session(db: DBSession, session_id: str) -> Session | None:
    return db.query(Session).filter(Session.id == session_id).first()


def list_sessions(db: DBSession, limit: int = 50) -> list[Session]:
    return db.query(Session).order_by(Session.created_at.desc()).limit(limit).all()


def delete_session(db: DBSession, session_id: str) -> bool:
    session = get_session(db, session_id)
    if not session:
        return False
    db.delete(session)
    db.flush()
    return True


def create_node(
    db: DBSession,
    session_id: str,
    role: str,
    content: str | None = None,
    parent_id: str | None = None,
    status: str = "pending",
) -> Node:
    branch_depth = 0
    if parent_id:
        parent = db.query(Node).filter(Node.id == parent_id).first()
        if parent:
            branch_depth = parent.branch_depth + 1

    node = Node(
        id=uuid4(),
        session_id=session_id,
        parent_id=parent_id,
        branch_depth=branch_depth,
        role=role,
        content=content,
        status=status,
    )
    db.add(node)
    db.flush()
    return node


def get_node(db: DBSession, node_id: str) -> Node | None:
    return db.query(Node).filter(Node.id == node_id).first()


def get_node_children(db: DBSession, node_id: str) -> list[Node]:
    return db.query(Node).filter(Node.parent_id == node_id).all()


def complete_node(
    db: DBSession,
    node_id: str,
    content: str | None = None,
    status: str = "completed",
    error_message: str | None = None,
):
    node = get_node(db, node_id)
    if not node:
        return
    node.status = status
    if content is not None:
        node.content = content
    if error_message:
        node.error_message = error_message
    node.completed_at = datetime.now(timezone.utc)
    db.flush()


def walk_parent_chain(db: DBSession, node_id: str) -> list[Node]:
    chain = []
    current = get_node(db, node_id)
    while current is not None:
        chain.append(current)
        if current.parent_id:
            current = get_node(db, str(current.parent_id))
        else:
            current = None
    chain.reverse()
    return chain


def assemble_messages_from_chain(
    db: DBSession,
    start_node_id: str | None,
    new_user_message: str,
    system_prompt: str = "",
) -> list[dict]:
    messages: list[dict] = []

    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    if start_node_id:
        chain = walk_parent_chain(db, start_node_id)
        for node in chain:
            if node.role in ("user", "assistant") and node.content:
                messages.append({"role": node.role, "content": node.content})

    messages.append({"role": "user", "content": new_user_message})
    return messages


def get_session_tree(db: DBSession, session_id: str) -> dict:
    nodes = db.query(Node).filter(Node.session_id == session_id).order_by(Node.created_at).all()
    children_map: dict[str, list[UUID]] = {}
    edges: list[dict[str, str]] = []

    for node in nodes:
        node_id_str = str(node.id)
        if node.parent_id:
            parent_id_str = str(node.parent_id)
            edges.append({"from": parent_id_str, "to": node_id_str})
            children_map.setdefault(parent_id_str, []).append(node.id)

    node_responses = []
    for node in nodes:
        node_responses.append({
            "id": node.id,
            "session_id": node.session_id,
            "parent_id": node.parent_id,
            "branch_depth": node.branch_depth,
            "role": node.role,
            "content": node.content,
            "thinking": node.thinking,
            "status": node.status,
            "error_message": node.error_message,
            "created_at": node.created_at,
            "completed_at": node.completed_at,
            "children_ids": children_map.get(str(node.id), []),
        })

    return {
        "session_id": session_id,
        "nodes": node_responses,
        "edges": edges,
    }
