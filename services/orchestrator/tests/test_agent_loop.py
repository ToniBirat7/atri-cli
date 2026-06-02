"""
Tests for services/orchestrator/agent_loop.py
"""
import asyncio
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

_ORCH_DIR = Path(__file__).resolve().parent.parent
if str(_ORCH_DIR) not in sys.path:
    sys.path.insert(0, str(_ORCH_DIR))

from agent_loop import AgentLoop, TurnOutcome
from hooks import HookRegistry
from config import OrchestratorConfig, LLMConfig, MCPConfig, AgentLoopConfig


# ── Minimal stubs ────────────────────────────────────────────────────────────────

@dataclass
class _FakeToolUse:
    tool_name: str
    tool_input: dict
    id: str = field(default_factory=lambda: f"fake_{uuid.uuid4().hex[:6]}")


class FakeLLMAdapter:
    """Minimal LLM adapter stub."""

    def __init__(self, content: str = "Final answer from test LLM."):
        self._content = content
        self.call_count = 0

    async def chat_completion(self, messages, tools=None, temperature=None, enable_thinking=False):
        self.call_count += 1
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": self._content,
                        "tool_calls": None,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    async def extract_tool_calls(self, completion) -> list:
        return []

    def format_tool_result(self, tool_name: str, result: Any, tool_call_id: Optional[str] = None) -> dict:
        return {"role": "tool", "name": tool_name, "content": str(result)}


class FakeMCPOrchestrator:
    """MCP orchestrator stub that records execute_tool calls."""

    def __init__(self):
        self.calls: list = []

    async def execute_tool(self, server_name, tool_name, tool_input, timeout_seconds=10, max_retries=0):
        self.calls.append({"server": server_name, "tool": tool_name, "input": tool_input})
        return f"result of {tool_name}"

    def get_proxy_tool_schema(self):
        return {"type": "function", "function": {"name": "mcp_proxy", "parameters": {}}}


class FakeToolRegistry:
    """Tool registry stub with no tools registered."""

    def to_openai_format(self) -> list:
        return []

    def get_tool(self, name: str):
        return None

    def resolve_tool_call(self, name: str):
        raise KeyError(f"Tool not found: {name}")


def _make_test_config(max_turns: int = 3) -> OrchestratorConfig:
    return OrchestratorConfig(
        llm=LLMConfig(
            base_url="http://127.0.0.1:19999/v1",
            model="test-model",
            max_tokens=512,
            timeout_seconds=5,
        ),
        agent_loop=AgentLoopConfig(max_turns=max_turns),
    )


# ── Single-turn, no tool calls ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_single_turn_plain_response():
    """Agent with no tools should return the LLM content directly."""
    config = _make_test_config(max_turns=3)
    registry = HookRegistry()  # empty — no builtin hooks to avoid side effects

    loop = AgentLoop(
        max_turns=3,
        enable_tool_use=False,
        config=config,
        hook_registry=registry,
    )
    adapter = FakeLLMAdapter("Hello from test!")
    mcp = FakeMCPOrchestrator()
    tool_reg = FakeToolRegistry()

    response, state = await loop.run(
        user_message="Say hello",
        llm_adapter=adapter,
        mcp_orchestrator=mcp,
        tool_registry=tool_reg,
        system_prompt="You are a test bot.",
    )

    assert "Hello from test!" in response
    assert state.status == "completed"
    assert state.turn >= 1


@pytest.mark.asyncio
async def test_single_turn_emits_events():
    """Event callback should receive turn_start and turn_final_response events."""
    events: list[dict] = []

    async def on_event(payload):
        events.append(payload)

    config = _make_test_config(max_turns=3)
    loop = AgentLoop(
        max_turns=3,
        enable_tool_use=False,
        config=config,
        hook_registry=HookRegistry(),
    )

    await loop.run(
        user_message="hello",
        llm_adapter=FakeLLMAdapter(),
        mcp_orchestrator=FakeMCPOrchestrator(),
        tool_registry=FakeToolRegistry(),
        event_callback=on_event,
    )

    event_types = {e["type"] for e in events}
    assert "turn_start" in event_types
    assert "turn_final_response" in event_types


# ── max_turns enforcement ───────────────────────────────────────────────────────

class _InfiniteToolLLM(FakeLLMAdapter):
    """LLM that always returns the same tool call (forces the loop to exhaust turns)."""

    async def extract_tool_calls(self, completion) -> list:
        return [_FakeToolUse("read_text_file", {"target_file_path": "/tmp/x.txt"})]

    async def chat_completion(self, messages, tools=None, temperature=None, enable_thinking=False):
        self.call_count += 1
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "read_text_file",
                                    "arguments": '{"target_file_path": "/tmp/x.txt"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }


@pytest.mark.asyncio
async def test_max_turns_stops_loop():
    """Loop should stop after max_turns even if the LLM always requests tool calls."""
    MAX = 2
    config = _make_test_config(max_turns=MAX)
    loop = AgentLoop(
        max_turns=MAX,
        enable_tool_use=True,
        config=config,
        hook_registry=HookRegistry(),
    )
    adapter = _InfiniteToolLLM()
    mcp = FakeMCPOrchestrator()
    tool_reg = FakeToolRegistry()

    _response, state = await loop.run(
        user_message="keep calling tools",
        llm_adapter=adapter,
        mcp_orchestrator=mcp,
        tool_registry=tool_reg,
    )

    assert state.turn <= MAX
    assert state.status == "completed"

    max_turns_outcomes = [
        t for t in state.turns_history if t.outcome == TurnOutcome.MAX_TURNS_REACHED
    ]
    assert max_turns_outcomes or state.turn == MAX


# ── Permission gating ───────────────────────────────────────────────────────────

def _mk_loop(mode: str) -> AgentLoop:
    return AgentLoop(
        max_turns=2,
        enable_tool_use=True,
        config=_make_test_config(),
        hook_registry=HookRegistry(),
        permission_mode=mode,
    )


def test_tool_requires_confirmation_by_mode():
    """Confirmation gating must follow the permission mode for each tool class."""
    default = _mk_loop("default")
    assert default._tool_requires_confirmation("delete_path") is True
    assert default._tool_requires_confirmation("bash_exec") is True
    assert default._tool_requires_confirmation("edit_file") is True
    assert default._tool_requires_confirmation("read_text_file") is False
    assert default._tool_requires_confirmation("list_directory") is False

    accept = _mk_loop("acceptEdits")
    assert accept._tool_requires_confirmation("delete_path") is True   # dangerous → confirm
    assert accept._tool_requires_confirmation("bash_exec") is True
    assert accept._tool_requires_confirmation("edit_file") is False    # edits auto-approved
    assert accept._tool_requires_confirmation("read_text_file") is False

    bypass = _mk_loop("bypassPermissions")
    assert bypass._tool_requires_confirmation("delete_path") is False
    assert bypass._tool_requires_confirmation("bash_exec") is False
    assert bypass._tool_requires_confirmation("edit_file") is False


class _DeleteToolRegistry(FakeToolRegistry):
    def resolve_tool_call(self, name: str):
        return ("local-mcp", name)


class _DeleteThenAnswerLLM(FakeLLMAdapter):
    """Emits one delete_path tool call, then a plain final answer."""

    async def chat_completion(self, messages, tools=None, temperature=None, enable_thinking=False):
        self.call_count += 1
        if self.call_count == 1:
            return {
                "choices": [{
                    "message": {"role": "assistant", "content": "",
                        "tool_calls": [{"id": "call_del", "type": "function",
                            "function": {"name": "delete_path", "arguments": '{"target_path": "x.txt"}'}}]},
                    "finish_reason": "tool_calls",
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
        return {
            "choices": [{"message": {"role": "assistant", "content": "OK, I won't delete it.", "tool_calls": None},
                "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    async def extract_tool_calls(self, completion) -> list:
        msg = completion["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        return [_FakeToolUse(c["function"]["name"], {"target_path": "x.txt"}, id=c["id"]) for c in calls]


@pytest.mark.asyncio
async def test_default_mode_denied_tool_not_executed():
    """A denied confirmation must prevent the tool from executing."""
    loop = _mk_loop("default")
    mcp = FakeMCPOrchestrator()

    async def on_event(payload):
        # Simulate the client declining the confirmation.
        if payload.get("type") == "tool_confirmation_requested":
            await loop.confirmation_queue.put({"request_id": payload["request_id"], "approved": False})

    await loop.run(
        user_message="delete x.txt",
        llm_adapter=_DeleteThenAnswerLLM(),
        mcp_orchestrator=mcp,
        tool_registry=_DeleteToolRegistry(),
        event_callback=on_event,
    )

    assert not any(c["tool"] == "delete_path" for c in mcp.calls), "denied tool must not run"


@pytest.mark.asyncio
async def test_default_mode_approved_tool_executes():
    """An approved confirmation must let the tool execute."""
    loop = _mk_loop("default")
    mcp = FakeMCPOrchestrator()

    async def on_event(payload):
        if payload.get("type") == "tool_confirmation_requested":
            await loop.confirmation_queue.put({"request_id": payload["request_id"], "approved": True})

    await loop.run(
        user_message="delete x.txt",
        llm_adapter=_DeleteThenAnswerLLM(),
        mcp_orchestrator=mcp,
        tool_registry=_DeleteToolRegistry(),
        event_callback=on_event,
    )

    assert any(c["tool"] == "delete_path" for c in mcp.calls), "approved tool must run"


# ── Malformed tool-call detection ────────────────────────────────────────────────

def test_looks_like_unparsed_tool_call():
    """Detect tool-call attempts that failed to parse (so the loop can retry)."""
    f = AgentLoop._looks_like_unparsed_tool_call
    # fenced JSON tool call
    assert f('```json\n{"name": "bash_exec", "arguments": {"command": "ls"}}\n```') is True
    # native Gemma marker
    assert f("<|tool_call>call:list_directory{target_path:<|\".\"|>}") is True
    # bare name+arguments (even if the JSON is malformed)
    assert f('{"name": "edit_file", "arguments": {"target_file_path": "a.py"') is True
    # plain prose answers are not tool calls
    assert f("The answer is 42.") is False
    assert f("Here is a summary of the file.") is False
    assert f("") is False
    # JSON that isn't a tool call shape
    assert f('{"foo": 1, "bar": 2}') is False


# ── GPU-only marker (placeholder) ───────────────────────────────────────────────

@pytest.mark.gpu_only
def test_gpu_placeholder():
    """Placeholder: real GPU tests would go here."""
    pytest.skip("GPU not available in CI")
