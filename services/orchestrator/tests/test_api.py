"""Tests for orchestrator API behavior."""

from collections import defaultdict, deque
import pytest
from types import SimpleNamespace

import api


class _FakeConfig:
    def __init__(self):
        self.llm = SimpleNamespace(model="test-model")
        self.agent_loop = SimpleNamespace(enable_thinking=False)
        self.prompt_policy = SimpleNamespace(
            default_profile="general-purpose",
            fallback_text="fallback",
            disclaimer_text="disclaimer",
            legal_help_line="help line",
        )
        self.auth = SimpleNamespace(
            mode="hybrid",
            jwt_secret=None,
            jwt_issuer="tarbar-ai",
            jwt_audience="tarbar-ai-orchestrator",
            service_subject="orchestrator-service",
        )
        self.security = SimpleNamespace(
            api_key=None,
            admin_api_key=None,
            rate_limit_per_minute=0,
            allow_unauthenticated_health=True,
        )


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


class _FakeConversationStore:
    def __init__(self):
        self.history_by_conversation = {
            "conv_existing": [
                {"role": "user", "content": "old question"},
                {"role": "assistant", "content": "old answer"},
            ]
        }

    async def ensure_conversation(self, conversation_id, prompt_profile):
        return None

    async def record_turn(self, **kwargs):
        return None

    async def list_conversations(self):
        return []

    async def build_chat_history_messages(self, conversation_id, max_turns=10):
        return self.history_by_conversation.get(conversation_id, [])

    async def get_conversation(self, conversation_id):
        if conversation_id != "conv_existing":
            return None
        return SimpleNamespace(
            conversation_id="conv_existing",
            prompt_profile="general-purpose",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )

    async def list_turns(self, conversation_id, limit=100):
        if conversation_id != "conv_existing":
            return []
        return [
            SimpleNamespace(
                turn_index=1,
                user_message="old question",
                assistant_response="old answer",
                status="completed",
                total_tool_calls=0,
                model="test-model",
                created_at="2026-01-01T00:00:00Z",
            )
        ]

    async def fork_conversation(self, source_conversation_id, target_conversation_id):
        return source_conversation_id == "conv_existing"


class _FakeAgentLoop:
    def __init__(self):
        self.max_turns = 10
        self.last_system_prompt = None
        self.prior_messages_seen = None

    async def run(self, user_message, llm_adapter, mcp_orchestrator, tool_registry, system_prompt=None, prior_messages=None, event_callback=None):
        self.last_system_prompt = system_prompt
        self.prior_messages_seen = prior_messages
        if event_callback is not None:
            await event_callback({"type": "turn_start", "turn": 1})
        return "ok", type("State", (), {"turn": 1, "total_tool_calls": 1, "status": "completed", "turns_history": []})()


class _FakeAgentLoopLong:
    def __init__(self):
        self.max_turns = 10
        self.last_system_prompt = None

    async def run(self, user_message, llm_adapter, mcp_orchestrator, tool_registry, system_prompt=None, prior_messages=None, event_callback=None):
        self.last_system_prompt = system_prompt
        if event_callback is not None:
            await event_callback({"type": "turn_start", "turn": 1})
            await event_callback({"type": "tool_call_start", "turn": 1, "tool_name": "list_directory"})
        return "abcdefghij" * 40, type("State", (), {"turn": 2, "total_tool_calls": 2, "status": "completed", "turns_history": []})()


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
    monkeypatch.setattr(api, "conversation_store", _FakeConversationStore())
    fake_loop = _FakeAgentLoop()
    monkeypatch.setattr(api, "agent_loop", fake_loop)

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
    assert fake_loop.last_system_prompt is not None


@pytest.mark.asyncio
async def test_chat_loads_prior_messages_for_existing_conversation(monkeypatch):
    monkeypatch.setattr(api, "config", _FakeConfig())
    monkeypatch.setattr(api, "llm_adapter", _FakeLLMAdapter())
    monkeypatch.setattr(api, "mcp_orchestrator", _FakeMCPOrchestrator())
    monkeypatch.setattr(api, "tool_registry", _FakeToolRegistry())
    monkeypatch.setattr(api, "conversation_store", _FakeConversationStore())
    fake_loop = _FakeAgentLoop()
    monkeypatch.setattr(api, "agent_loop", fake_loop)

    async def noop_execute_tool(server_name, tool_name, tool_input):
        return "ok"

    monkeypatch.setattr(api.mcp_orchestrator, "execute_tool", noop_execute_tool)

    await api.chat(
        api.ChatRequest(message="continue", conversation_id="conv_existing"),
        _FakeRequest(),
    )

    assert fake_loop.prior_messages_seen is not None
    assert len(fake_loop.prior_messages_seen) == 2
    assert fake_loop.prior_messages_seen[0]["content"] == "old question"


@pytest.mark.asyncio
async def test_chat_rejects_prompt_profile_override_without_admin(monkeypatch):
    monkeypatch.setattr(api, "config", _FakeConfig())
    monkeypatch.setattr(api, "llm_adapter", _FakeLLMAdapter())
    monkeypatch.setattr(api, "mcp_orchestrator", _FakeMCPOrchestrator())
    monkeypatch.setattr(api, "tool_registry", _FakeToolRegistry())
    monkeypatch.setattr(api, "agent_loop", _FakeAgentLoop())

    with pytest.raises(api.HTTPException) as exc_info:
        await api.chat(api.ChatRequest(message="hello", prompt_profile="legal-strict"), _FakeRequest())

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_chat_accepts_admin_prompt_profile_override(monkeypatch):
    config = _FakeConfig()
    config.security.admin_api_key = "admin-secret"
    monkeypatch.setattr(api, "config", config)
    monkeypatch.setattr(api, "llm_adapter", _FakeLLMAdapter())
    monkeypatch.setattr(api, "mcp_orchestrator", _FakeMCPOrchestrator())
    monkeypatch.setattr(api, "tool_registry", _FakeToolRegistry())
    fake_loop = _FakeAgentLoop()
    monkeypatch.setattr(api, "agent_loop", fake_loop)

    async def noop_execute_tool(server_name, tool_name, tool_input):
        return "ok"

    monkeypatch.setattr(api.mcp_orchestrator, "execute_tool", noop_execute_tool)

    response = await api.chat(
        api.ChatRequest(message="hello", prompt_profile="legal-strict"),
        _FakeRequest(headers={"authorization": "Bearer admin-secret"}),
    )

    assert response.request_id
    assert fake_loop.last_system_prompt is not None
    assert "legal information assistant" in fake_loop.last_system_prompt.lower()


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
    assert '"event"' in body
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


@pytest.mark.asyncio
async def test_get_conversation_details(monkeypatch):
    monkeypatch.setattr(api, "config", _FakeConfig())
    monkeypatch.setattr(api, "conversation_store", _FakeConversationStore())

    response = await api.get_conversation("conv_existing", _FakeRequest(path="/conversations/conv_existing"))
    assert response.conversation.conversation_id == "conv_existing"
    assert len(response.turns) == 1


@pytest.mark.asyncio
async def test_resume_and_fork_conversation(monkeypatch):
    monkeypatch.setattr(api, "config", _FakeConfig())
    monkeypatch.setattr(api, "conversation_store", _FakeConversationStore())

    resumed = await api.resume_conversation("conv_existing", _FakeRequest(path="/conversations/conv_existing/resume"))
    assert resumed.turn_count == 1

    forked = await api.fork_conversation(
        "conv_existing",
        api.ConversationForkRequest(new_conversation_id="conv_forked"),
        _FakeRequest(path="/conversations/conv_existing/fork"),
    )
    assert forked.new_conversation_id == "conv_forked"


@pytest.mark.asyncio
async def test_permissions_evaluate_endpoint(monkeypatch):
    monkeypatch.setattr(api, "config", _FakeConfig())

    result = await api.permissions_evaluate(
        api.PermissionsEvaluateRequest(
            tool_call="Bash(git push origin main)",
            mode="default",
            allow=["Bash(git status*)"],
            ask=["Bash(git push*)"],
            deny=[],
        ),
        _FakeRequest(path="/permissions/evaluate"),
    )

    assert result.action == "ask"
