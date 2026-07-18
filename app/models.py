import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Text, Integer, DateTime, ForeignKey, Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


def _new_uuid():
    return uuid.uuid4()


class Session(Base):
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    title = Column(String(255), nullable=True)
    metadata_json = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow)

    nodes = relationship("Node", back_populates="session", cascade="all, delete-orphan")
    events = relationship("AgentEvent", back_populates="session", cascade="all, delete-orphan")
    tool_calls = relationship("ToolCall", back_populates="session", cascade="all, delete-orphan")


class Node(Base):
    __tablename__ = "nodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    parent_id = Column(UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True)
    branch_depth = Column(Integer, default=0)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=True)
    thinking = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    session = relationship("Session", back_populates="nodes")
    children = relationship("Node", backref="parent", remote_side=[id])
    events = relationship("AgentEvent", back_populates="node", cascade="all, delete-orphan")
    tool_calls = relationship("ToolCall", back_populates="node", cascade="all, delete-orphan")


class AgentEvent(Base):
    __tablename__ = "agent_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    seq = Column(Integer, nullable=False)
    event_type = Column(String(30), nullable=False)
    payload_json = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("idx_events_node_seq", "node_id", "seq"),
    )

    session = relationship("Session", back_populates="events")
    node = relationship("Node", back_populates="events")


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    node_id = Column(UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    tool_name = Column(String(100), nullable=False)
    arguments_json = Column(JSONB, nullable=False)
    result_json = Column(JSONB, nullable=True)
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    session = relationship("Session", back_populates="tool_calls")
    node = relationship("Node", back_populates="tool_calls")
