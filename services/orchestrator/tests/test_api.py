"""Tests for orchestrator API behavior."""

from collections import defaultdict, deque
import pytest

import api


class _FakeConfig:
    class llm:
        model = "test-model"

    class security:
        api_key = None
        rate_limit_per_minute = 0
        allow_unauthenticated_health = True


class _FakeLLMAdapter:
    async def close(self):
        return None

    async def client_get(self, path):
        return None


class _FakeMCPOrchestrator:
    def __init__(self):
        self._status = {"local-mcp": {"status": "initialized", "mode": "inprocess-module"}}

    async def shutdown_all(self):
        return None

    async def execute_tool(self, server_name, tool_name, tool_input):
        if tool_name == "set_allowed_directory":
            return "ok"
        if tool_name == "list_directory":
            return '{"path": ".", "entries": [{"name": "alpha"}, {"name": "beta"}, {"name": "gamma"}]}'
        return "ok"

    def get_server_status(self):
        return self._status


class _FakeToolRegistry:
    def list_all_tools(self):
        return []


class _FakeAgentLoop:
    def __init__(self):
        self.max_turns = 10

    async def run(self, user_message, llm_adapter, mcp_orchestrator, tool_registry):
        return "ok", type("State", (), {"turn": 1, "total_tool_calls": 1, "status": "completed"})()


class _FakeAgentLoopLong:
    def __init__(self):
        self.max_turns = 10

    async def run(self, user_message, llm_adapter, mcp_orchestrator, tool_registry):
        return "abcdefghij" * 40, type("State", (), {"turn": 2, "total_tool_calls": 2, "status": "completed"})()


class _FakeRequest:
    def __init__(self, headers=None, path="/chat", client_host="127.0.0.1"):
        self.headers = headers or {}
        self.url = type("Url", (), {"path": path})()
        self.client = type("Client", (), {"host": client_host})()


@pytest.mark.asyncio
async def test_metrics_endpoint_counts(monkeypatch):
    monkeypatch.setattr(api, "service_started_at", 0.0)
    monkeypatch.setattr(api, "chat_requests_total", 3)
    monkeypatch.setattr(api, "chat_requests_succeeded", 2)
    monkeypatch.setattr(api, "chat_requests_failed", 1)
    monkeypatch.setattr(api, "total_tool_calls", 7)
    monkeypatch.setattr(api, "mcp_orchestrator", _FakeMCPOrchestrator())

    metrics = await api.metrics(_FakeRequest(path="/metrics"))

    assert metrics.chat_requests_total == 3
    assert metrics.chat_requests_succeeded == 2
    assert metrics.chat_requests_failed == 1
    assert metrics.total_tool_calls == 7
    assert metrics.active_mcp_servers == 1


@pytest.mark.asyncio
async def test_chat_returns_request_id_and_default_directory(monkeypatch):
    monkeypatch.setattr(api, "config", _FakeConfig())
    monkeypatch.setattr(api, "llm_adapter", _FakeLLMAdapter())
    monkeypatch.setattr(api, "mcp_orchestrator", _FakeMCPOrchestrator())
    monkeypatch.setattr(api, "tool_registry", _FakeToolRegistry())
    monkeypatch.setattr(api, "agent_loop", _FakeAgentLoop())

    captured = {}

    async def fake_execute_tool(server_name, tool_name, tool_input):
        captured["server_name"] = server_name
        captured["tool_name"] = tool_name
        captured["tool_input"] = tool_input
        return "ok"

    monkeypatch.setattr(api.mcp_orchestrator, "execute_tool", fake_execute_tool)

    response = await api.chat(api.ChatRequest(message="hello"), _FakeRequest())

    assert response.request_id
    assert response.model == "test-model"
    assert captured["tool_name"] == "set_allowed_directory"
    assert captured["tool_input"]["path"]


@pytest.mark.asyncio
async def test_chat_restores_max_turns(monkeypatch):
    fake_loop = _FakeAgentLoop()
    monkeypatch.setattr(api, "config", _FakeConfig())
    monkeypatch.setattr(api, "llm_adapter", _FakeLLMAdapter())
    monkeypatch.setattr(api, "mcp_orchestrator", _FakeMCPOrchestrator())
    monkeypatch.setattr(api, "tool_registry", _FakeToolRegistry())
    monkeypatch.setattr(api, "agent_loop", fake_loop)

    async def noop_execute_tool(server_name, tool_name, tool_input):
        return "ok"

    monkeypatch.setattr(api.mcp_orchestrator, "execute_tool", noop_execute_tool)

    await api.chat(api.ChatRequest(message="hello", max_turns=4), _FakeRequest())

    assert fake_loop.max_turns == 10


@pytest.mark.asyncio
async def test_chat_requires_api_key_when_configured(monkeypatch):
    config = _FakeConfig()
    config.security.api_key = "secret"
    monkeypatch.setattr(api, "config", config)
    monkeypatch.setattr(api, "llm_adapter", _FakeLLMAdapter())
    monkeypatch.setattr(api, "mcp_orchestrator", _FakeMCPOrchestrator())
    monkeypatch.setattr(api, "tool_registry", _FakeToolRegistry())
    monkeypatch.setattr(api, "agent_loop", _FakeAgentLoop())

    with pytest.raises(api.HTTPException) as exc_info:
        await api.chat(api.ChatRequest(message="hello"), _FakeRequest())

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_chat_accepts_bearer_api_key(monkeypatch):
    config = _FakeConfig()
    config.security.api_key = "secret"
    monkeypatch.setattr(api, "config", config)
    monkeypatch.setattr(api, "llm_adapter", _FakeLLMAdapter())
    monkeypatch.setattr(api, "mcp_orchestrator", _FakeMCPOrchestrator())
    monkeypatch.setattr(api, "tool_registry", _FakeToolRegistry())
    monkeypatch.setattr(api, "agent_loop", _FakeAgentLoop())

    async def noop_execute_tool(server_name, tool_name, tool_input):
        return "ok"

    monkeypatch.setattr(api.mcp_orchestrator, "execute_tool", noop_execute_tool)

    response = await api.chat(
        api.ChatRequest(message="hello"),
        _FakeRequest(headers={"authorization": "Bearer secret"}),
    )

    assert response.request_id


@pytest.mark.asyncio
async def test_chat_rate_limits_per_client(monkeypatch):
    config = _FakeConfig()
    config.security.rate_limit_per_minute = 1
    monkeypatch.setattr(api, "config", config)
    monkeypatch.setattr(api, "rate_limit_windows", defaultdict(deque))
    monkeypatch.setattr(api, "llm_adapter", _FakeLLMAdapter())
    monkeypatch.setattr(api, "mcp_orchestrator", _FakeMCPOrchestrator())
    monkeypatch.setattr(api, "tool_registry", _FakeToolRegistry())
    monkeypatch.setattr(api, "agent_loop", _FakeAgentLoop())

    async def noop_execute_tool(server_name, tool_name, tool_input):
        return "ok"

    monkeypatch.setattr(api.mcp_orchestrator, "execute_tool", noop_execute_tool)

    request = _FakeRequest(headers={"authorization": "Bearer secret"})
    await api.chat(api.ChatRequest(message="hello"), request)

    with pytest.raises(api.HTTPException) as exc_info:
        await api.chat(api.ChatRequest(message="hello"), request)

    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_chat_stream_emits_chunks_and_done(monkeypatch):
    config = _FakeConfig()
    config.security.api_key = None
    config.security.rate_limit_per_minute = 0
    monkeypatch.setattr(api, "config", config)
    monkeypatch.setattr(api, "llm_adapter", _FakeLLMAdapter())
    monkeypatch.setattr(api, "mcp_orchestrator", _FakeMCPOrchestrator())
    monkeypatch.setattr(api, "tool_registry", _FakeToolRegistry())
    monkeypatch.setattr(api, "agent_loop", _FakeAgentLoopLong())

    async def noop_execute_tool(server_name, tool_name, tool_input):
        return "ok"

    monkeypatch.setattr(api.mcp_orchestrator, "execute_tool", noop_execute_tool)

    response = await api.chat_stream(api.ChatRequest(message="hello"), _FakeRequest(path="/chat/stream"))

    chunks = []
    async for item in response.body_iterator:
        chunks.append(item)

    body = "".join(chunks)
    assert "request_id" in body
    assert "content" in body
    assert "[DONE]" in body


@pytest.mark.asyncio
async def test_ready_and_live(monkeypatch):
    monkeypatch.setattr(api, "config", _FakeConfig())
    monkeypatch.setattr(api, "llm_adapter", _FakeLLMAdapter())
    monkeypatch.setattr(api, "mcp_orchestrator", _FakeMCPOrchestrator())
    monkeypatch.setattr(api, "tool_registry", _FakeToolRegistry())

    assert (await api.live())["status"] == "alive"
    assert (await api.ready())["status"] == "ready"
