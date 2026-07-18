from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.models import AgentEvent, ToolCall


def persist_events(db: DBSession, events: list[dict]) -> int:
    seq_by_node: dict[str, int] = {}
    tool_call_records: list[dict] = []
    count = 0

    for evt in events:
        node_id = evt["node_id"]
        seq_by_node.setdefault(node_id, 0)
        seq = seq_by_node[node_id]
        seq_by_node[node_id] = seq + 1

        payload = evt.get("payload", evt.get("payload_json", {}))
        ae = AgentEvent(
            id=uuid4(),
            session_id=evt["session_id"],
            node_id=node_id,
            seq=seq,
            event_type=evt["event_type"],
            payload_json=payload,
        )
        db.add(ae)
        count += 1

        if evt["event_type"] == "tool_call":
            tool_call_records.append({
                "node_id": node_id,
                "session_id": evt["session_id"],
                "tool_name": payload.get("tool_name", ""),
                "arguments_json": payload.get("arguments", {}),
            })

    return count
