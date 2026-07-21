"""event_bus.py 的测试。运行方式：pytest tests/unit/test_event_bus.py -v"""

import asyncio

import pytest

from app.core.event_bus import EventBus, get_event_bus
from app.core.event_types import EventType


# ─── subscribe + emit ──────────────────────────────────

@pytest.mark.asyncio
async def test_emit_delivers_to_subscriber():
    """订阅后 emit 应把事件推送到队列。"""
    bus = EventBus()
    q = asyncio.Queue(maxsize=10)
    bus.subscribe("s1", q)

    await bus.emit("n1", "s1", EventType.TEXT, {"content": "hello"})

    event = q.get_nowait()
    assert event["node_id"] == "n1"
    assert event["session_id"] == "s1"
    assert event["type"] == "text"
    assert event["content"] == "hello"
    assert "timestamp" in event


@pytest.mark.asyncio
async def test_emit_to_multiple_subscribers():
    """同一 session 的多个队列都应收到事件。"""
    bus = EventBus()
    q1 = asyncio.Queue(maxsize=10)
    q2 = asyncio.Queue(maxsize=10)
    bus.subscribe("s1", q1)
    bus.subscribe("s1", q2)

    await bus.emit("n1", "s1", EventType.STATUS, {"status": "ok"})

    assert not q1.empty()
    assert not q2.empty()
    assert q1.get_nowait()["status"] == "ok"
    assert q2.get_nowait()["status"] == "ok"


@pytest.mark.asyncio
async def test_different_sessions_isolated():
    """A session 的事件不应推送到 B session 的队列。"""
    bus = EventBus()
    q_a = asyncio.Queue(maxsize=10)
    q_b = asyncio.Queue(maxsize=10)
    bus.subscribe("a", q_a)
    bus.subscribe("b", q_b)

    await bus.emit("n1", "a", EventType.TEXT, {"content": "only for a"})

    assert not q_a.empty()
    assert q_b.empty()  # B 不应收到


@pytest.mark.asyncio
async def test_emit_no_subscribers_does_not_raise():
    """没有订阅者时 emit 不应抛异常。"""
    bus = EventBus()
    await bus.emit("n1", "no_one", EventType.TEXT, {"content": "nobody"})


@pytest.mark.asyncio
async def test_emit_full_queue_graceful():
    """队列满时 emit 应静默丢弃，不抛异常、不阻塞。"""
    bus = EventBus()
    q = asyncio.Queue(maxsize=1)  # 容量 1
    bus.subscribe("s1", q)

    await bus.emit("n1", "s1", EventType.TEXT, {"seq": 1})
    # 队列已满，这次 emit 应静默丢弃
    await bus.emit("n1", "s1", EventType.TEXT, {"seq": 2})

    event = q.get_nowait()
    assert event["seq"] == 1  # 第一条在，第二条丢了


# ─── unsubscribe ────────────────────────────────────────

@pytest.mark.asyncio
async def test_unsubscribe_stops_events():
    """取消订阅后不再收到事件。"""
    bus = EventBus()
    q = asyncio.Queue(maxsize=10)
    bus.subscribe("s1", q)
    bus.unsubscribe("s1", q)

    await bus.emit("n1", "s1", EventType.TEXT, {"content": "should not arrive"})

    assert q.empty()


@pytest.mark.asyncio
async def test_unsubscribe_nonexistent_does_not_raise():
    """取消不存在的订阅不应抛异常。"""
    bus = EventBus()
    q = asyncio.Queue(maxsize=10)
    bus.unsubscribe("no_session", q)  # 不抛异常
    bus.subscribe("s1", asyncio.Queue(maxsize=10))
    bus.unsubscribe("s1", q)  # session 存在但 queue 未订阅，也不抛异常


@pytest.mark.asyncio
async def test_unsubscribe_removes_only_specified_queue():
    """取消一个队列不影响同一 session 的其他队列。"""
    bus = EventBus()
    q1 = asyncio.Queue(maxsize=10)
    q2 = asyncio.Queue(maxsize=10)
    bus.subscribe("s1", q1)
    bus.subscribe("s1", q2)
    bus.unsubscribe("s1", q1)

    await bus.emit("n1", "s1", EventType.TEXT, {"content": "hi"})

    assert q1.empty()
    assert not q2.empty()


# ─── payload 展开 ───────────────────────────────────────

@pytest.mark.asyncio
async def test_emit_payload_spread_into_event():
    """payload 的键应展开到事件的顶层。"""
    bus = EventBus()
    q = asyncio.Queue(maxsize=10)
    bus.subscribe("s1", q)

    await bus.emit("n1", "s1", EventType.TOOL_RESULT, {
        "tool_name": "search",
        "result": "found",
        "duration_ms": 150,
    })

    event = q.get_nowait()
    assert event["tool_name"] == "search"
    assert event["result"] == "found"
    assert event["duration_ms"] == 150
    assert event["type"] == "tool_result"


# ─── flush_events ───────────────────────────────────────

def test_flush_events_returns_list():
    """flush_events 应返回 list。"""
    bus = EventBus()
    result = bus.flush_events()
    assert isinstance(result, list)


# ─── get_event_bus 全局单例 ─────────────────────────────

def test_get_event_bus_returns_singleton():
    """多次调用返回同一个实例。"""
    b1 = get_event_bus()
    b2 = get_event_bus()
    assert b1 is b2
