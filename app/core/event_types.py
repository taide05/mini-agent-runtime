from __future__ import annotations

from enum import Enum


class EventType(str, Enum):
    THINKING = "thinking"
    TEXT = "text"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    STATUS = "status"


class StopReason(str, Enum):
    FINISH = "finish"
    MAX_ITERATIONS = "max_iterations"
    ERROR = "error"
    INTERRUPTED = "interrupted"
