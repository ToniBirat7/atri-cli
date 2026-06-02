"""
Shared pytest fixtures for the orchestrator test suite.
"""
import sys
from pathlib import Path

import pytest

# Ensure orchestrator package is importable when running from repo root
_ORCH_DIR = Path(__file__).resolve().parent.parent
if str(_ORCH_DIR) not in sys.path:
    sys.path.insert(0, str(_ORCH_DIR))

from config import (
    OrchestratorConfig,
    LLMConfig,
    MCPConfig,
    AgentLoopConfig,
    PromptPolicyConfig,
    DatabaseConfig,
    AuthConfig,
    RedisConfig,
    TelemetryConfig,
    SecurityConfig,
    HookConfig,
    ManagedSettingsConfig,
)


@pytest.fixture
def test_config() -> OrchestratorConfig:
    """Return an OrchestratorConfig with safe test values (no real services required)."""
    return OrchestratorConfig(
        llm=LLMConfig(
            base_url="http://127.0.0.1:19999/v1",
            api_key="test-key",
            model="test-model",
            temperature=0.6,
            max_tokens=512,
            timeout_seconds=5,
        ),
        mcp=MCPConfig(
            servers=[],
            tool_timeout_seconds=5,
            max_tool_call_retries=0,
        ),
        agent_loop=AgentLoopConfig(
            max_turns=3,
            max_tool_calls_per_turn=2,
            enable_tool_use=True,
        ),
        prompt_policy=PromptPolicyConfig(),
        database=DatabaseConfig(
            url="sqlite:///:memory:",
            enable_persistence=False,
        ),
        auth=AuthConfig(mode="hybrid", jwt_secret="test-secret"),
        redis=RedisConfig(enabled=False),
        telemetry=TelemetryConfig(enabled=False),
        security=SecurityConfig(),
        hooks=HookConfig(enabled=True),
        managed_settings=ManagedSettingsConfig(),
        log_level="WARNING",
    )


# ---------------------------------------------------------------------------
# Minimal fake LLM completion factory
# ---------------------------------------------------------------------------

def make_plain_completion(content: str = "Hello from the test LLM!") -> dict:
    """Return an OpenAI-shaped completion dict with no tool calls."""
    return {
        "id": "test-completion",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": None,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }
