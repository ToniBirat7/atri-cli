"""Tests for OrchestratorConfig defaults and env overrides."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import OrchestratorConfig, AgentLoopConfig


def test_default_thinking_mode():
    c = AgentLoopConfig()
    assert c.thinking_mode == "tool_calls_off"


def test_default_max_turns():
    c = AgentLoopConfig()
    assert c.max_turns == 10


def test_default_max_tool_calls():
    c = AgentLoopConfig()
    assert c.max_tool_calls_per_turn == 3


def test_from_env_reads_thinking_mode(monkeypatch):
    monkeypatch.setenv("AGENT_THINKING_MODE", "always")
    c = OrchestratorConfig.from_env()
    assert c.agent_loop.thinking_mode == "always"


def test_from_env_reads_max_turns(monkeypatch):
    monkeypatch.setenv("AGENT_MAX_TURNS", "5")
    c = OrchestratorConfig.from_env()
    assert c.agent_loop.max_turns == 5


def test_llm_default_temperature():
    from config import LLMConfig
    c = LLMConfig()
    assert c.temperature == 0.6


def test_llm_default_top_k():
    from config import LLMConfig
    c = LLMConfig()
    assert c.top_k == 64


def test_bad_numeric_env_falls_back_to_default(monkeypatch):
    """A non-numeric env value must not crash startup — fall back to the default."""
    monkeypatch.setenv("LLM_MAX_TOKENS", "auto")
    monkeypatch.setenv("AGENT_MAX_TURNS", "xyz")
    monkeypatch.setenv("LLM_TEMPERATURE", "hot")
    c = OrchestratorConfig.from_env()
    assert c.llm.max_tokens == 2048      # default
    assert c.agent_loop.max_turns == 10  # default
    assert c.llm.temperature == 0.6      # default


def test_env_int_float_helpers():
    from config import _env_int, _env_float
    import os
    os.environ.pop("ATRI_TEST_NUM", None)
    assert _env_int("ATRI_TEST_NUM", 7) == 7          # missing -> default
    assert _env_float("ATRI_TEST_NUM", 1.5) == 1.5
    os.environ["ATRI_TEST_NUM"] = "42"
    try:
        assert _env_int("ATRI_TEST_NUM", 7) == 42     # valid -> parsed
        os.environ["ATRI_TEST_NUM"] = "nope"
        assert _env_int("ATRI_TEST_NUM", 7) == 7      # invalid -> default
    finally:
        os.environ.pop("ATRI_TEST_NUM", None)
