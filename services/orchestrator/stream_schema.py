"""Shared SSE stream schema helpers for chat streaming."""

from __future__ import annotations

import json
from typing import Any, Dict


def encode_sse_data(payload: Dict[str, Any]) -> str:
    """Encode a JSON payload into SSE data format."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def stream_event_request_started(request_id: str) -> Dict[str, Any]:
    """Create request-started event payload."""
    return {
        "type": "request_started",
        "request_id": request_id,
    }


def stream_event_session_started(conversation_id: str) -> Dict[str, Any]:
    """Create session-started event payload."""
    return {
        "type": "session_started",
        "conversation_id": conversation_id,
    }


def stream_event_progress(event: Dict[str, Any]) -> Dict[str, Any]:
    """Create agent-progress event payload."""
    return {
        "type": "agent_event",
        "event": event,
    }


def stream_event_assistant_delta(content: str) -> Dict[str, Any]:
    """Create assistant-delta event payload."""
    return {
        "type": "assistant_delta",
        "content": content,
    }


def stream_event_error(message: str) -> Dict[str, Any]:
    """Create error event payload."""
    return {
        "type": "error",
        "error": message,
    }


def stream_event_usage(
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
) -> Dict[str, Any]:
    """Create usage event payload."""
    return {
        "type": "usage",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }
