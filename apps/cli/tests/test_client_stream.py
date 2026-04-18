from __future__ import annotations

import json

from tarbar_cli.client import OrchestratorClient


class _FakeResponse:
    def __init__(self, lines: list[str]):
        self._lines = [line.encode("utf-8") for line in lines]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        return iter(self._lines)


def test_stream_chat_normalizes_typed_envelopes(monkeypatch):
    client = OrchestratorClient(base_url="http://localhost:8001")
    lines = [
        f"data: {json.dumps({'type': 'request_started', 'request_id': 'req_1'})}\n",
        f"data: {json.dumps({'type': 'session_started', 'conversation_id': 'conv_1'})}\n",
        f"data: {json.dumps({'type': 'agent_event', 'event': {'type': 'turn_start', 'turn': 1}})}\n",
        f"data: {json.dumps({'type': 'assistant_delta', 'content': 'Hello'})}\n",
        f"data: {json.dumps({'type': 'error', 'error': 'boom'})}\n",
        "data: [DONE]\n",
    ]

    def _fake_urlopen(_req, timeout=300):
        return _FakeResponse(lines)

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    events = list(client.stream_chat({"message": "hi"}))

    assert events[0] == {"request_id": "req_1"}
    assert events[1] == {"conversation_id": "conv_1"}
    assert events[2] == {"event": {"type": "turn_start", "turn": 1}}
    assert events[3] == {"content": "Hello"}
    assert events[4] == {"error": "boom"}
    assert events[5] == {"done": True}


def test_stream_chat_keeps_legacy_envelopes(monkeypatch):
    client = OrchestratorClient(base_url="http://localhost:8001")
    lines = [
        f"data: {json.dumps({'conversation_id': 'conv_legacy'})}\n",
        f"data: {json.dumps({'content': 'chunk'})}\n",
        "data: [DONE]\n",
    ]

    def _fake_urlopen(_req, timeout=300):
        return _FakeResponse(lines)

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    events = list(client.stream_chat({"message": "hi"}))

    assert events[0] == {"conversation_id": "conv_legacy"}
    assert events[1] == {"content": "chunk"}
    assert events[2] == {"done": True}


def test_stream_chat_marks_non_dict_json_as_malformed(monkeypatch):
    client = OrchestratorClient(base_url="http://localhost:8001")
    lines = [
        "data: 123\n",
        "data: [DONE]\n",
    ]

    def _fake_urlopen(_req, timeout=300):
        return _FakeResponse(lines)

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    events = list(client.stream_chat({"message": "hi"}))

    assert events[0] == {"malformed": "123"}
    assert events[1] == {"done": True}
