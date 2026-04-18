from __future__ import annotations

from stream_schema import (
    encode_sse_data,
    stream_event_assistant_delta,
    stream_event_error,
    stream_event_progress,
    stream_event_request_started,
    stream_event_session_started,
    stream_event_usage,
)


def test_stream_event_request_started_shape():
    payload = stream_event_request_started("req_123")
    assert payload["type"] == "request_started"
    assert payload["request_id"] == "req_123"


def test_stream_event_session_started_shape():
    payload = stream_event_session_started("conv_123")
    assert payload["type"] == "session_started"
    assert payload["conversation_id"] == "conv_123"


def test_stream_event_progress_preserves_event_payload():
    event = {"type": "turn_start", "turn": 1}
    payload = stream_event_progress(event)
    assert payload["type"] == "agent_event"
    assert payload["event"] == event


def test_stream_event_assistant_delta_shape():
    payload = stream_event_assistant_delta("hello")
    assert payload["type"] == "assistant_delta"
    assert payload["content"] == "hello"


def test_stream_event_error_shape():
    payload = stream_event_error("boom")
    assert payload["type"] == "error"
    assert payload["error"] == "boom"


def test_stream_event_usage_shape():
    payload = stream_event_usage(100, 25, 125)
    assert payload["type"] == "usage"
    assert payload["prompt_tokens"] == 100
    assert payload["completion_tokens"] == 25
    assert payload["total_tokens"] == 125


def test_encode_sse_data_wraps_json_line():
    line = encode_sse_data({"type": "assistant_delta", "content": "hi"})
    assert line.startswith("data: {")
    assert line.endswith("\n\n")
    assert '"type": "assistant_delta"' in line
