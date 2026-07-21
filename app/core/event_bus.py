"""事件总线。

Agent 循环过程中每发生一件事就通过 EventBus 推送出去，
订阅者（如 SSE 连接）收到事件后推给前端。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from app.core.event_types import EventType


class EventBus:

    def subscribe(self, session_id: str, queue: asyncio.Queue) -> None:
        if not hasattr(self,"_subscribers"):
            self._subscribers = {}
        if session_id not in self._subscribers:
            self._subscribers[session_id] = []
        self._subscribers[session_id].append(queue)

    def unsubscribe(self, session_id: str, queue: asyncio.Queue) -> None:
        if not hasattr(self, "_subscribers"):
            return
        if session_id in self._subscribers:
            if queue in self._subscribers[session_id]:
                self._subscribers[session_id].remove(queue)

    async def emit(
        self,
        node_id: str,
        session_id: str,
        event_type: EventType,
        payload: dict[str, Any],
    ) -> None:
        event_data = {
            "node_id": str(node_id),
            "session_id": str(session_id),
            "type": event_type.value,   # EventType 是 str enum, .value 拿字符串
            **payload,                   # payload 的键值展开到事件顶层的其余字段
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        if not hasattr(self,"_pending_events"):
            self._pending_events = []
        self._pending_events.append(event_data)
        if not hasattr(self,"_subscribers"):
            return
        for queue in self._subscribers.get(session_id,[]):
            try:
                queue.put_nowait(event_data)
            except asyncio.QueueFull:
                pass

    def flush_events(self) -> list[dict]:
        if not hasattr(self,"_pending_events"):
            return []
        result = self._pending_events
        self._pending_events = []
        return result

# ─── 全局单例（已给，直接用）─────────────────────────────

_global_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """获取全局唯一的 EventBus 实例。"""
    global _global_event_bus
    if _global_event_bus is None:
        _global_event_bus = EventBus()
    return _global_event_bus
