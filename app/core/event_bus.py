from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.core.event_types import EventType


class EventBus:
    def __init__(self):
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._pending_events: list[dict] = []

    def subscribe(self, session_id: str, queue: asyncio.Queue):
        if session_id not in self._subscribers:
            self._subscribers[session_id] = []
        self._subscribers[session_id].append(queue)

    def unsubscribe(self, session_id: str, queue: asyncio.Queue):
        if session_id in self._subscribers:
            subs = self._subscribers[session_id]
            if queue in subs:
                subs.remove(queue)

    async def emit(
        self,
        node_id: str,
        session_id: str,
        event_type: EventType,
        payload: dict[str, Any],
    ):
        event_data = {
            "node_id": str(node_id),
            "session_id": str(session_id),
            "type": event_type.value,
            **payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._pending_events.append({
            "session_id": session_id,
            "node_id": node_id,
            "event_type": event_type.value,
            "payload": payload,
        })

        for queue in self._subscribers.get(session_id, []):
            try:
                queue.put_nowait(event_data)
            except asyncio.QueueFull:
                pass

    def flush_events(self) -> list[dict]:
        events = self._pending_events.copy()
        self._pending_events.clear()
        return events


_global_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _global_event_bus
    if _global_event_bus is None:
        _global_event_bus = EventBus()
    return _global_event_bus
