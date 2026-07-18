from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ─── Session ───

class SessionCreate(BaseModel):
    title: str | None = None
    system_prompt: str | None = None
    model: str = "deepseek-chat"
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionResponse(BaseModel):
    id: UUID
    title: str | None = None
    created_at: datetime
    updated_at: datetime
    node_count: int = 0

    model_config = {"from_attributes": True}


# ─── Node ───

class NodeResponse(BaseModel):
    id: UUID
    session_id: UUID
    parent_id: UUID | None = None
    branch_depth: int
    role: str
    content: str | None = None
    thinking: str | None = None
    status: str
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    children_ids: list[UUID] = Field(default_factory=list)

    model_config = {"from_attributes": True}


# ─── Agent Run ───

class AgentRunRequest(BaseModel):
    content: str
    parent_id: UUID | None = None


class AgentRunResponse(BaseModel):
    node_id: UUID
    session_id: UUID
    status: str


# ─── Branch ───

class BranchRequest(BaseModel):
    parent_node_id: UUID
    content: str
    role: str = "user"


# ─── Tool ───

class ToolDefinitionSchema(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


class ToolRegisterRequest(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


class ToolListResponse(BaseModel):
    tools: list[ToolDefinitionSchema]


# ─── Event ───

class EventResponse(BaseModel):
    id: UUID
    node_id: UUID
    seq: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Session Tree ───

class SessionTreeResponse(BaseModel):
    session_id: UUID
    nodes: list[NodeResponse]
    edges: list[dict[str, UUID]]
