"""Tests for OrchestratorConfig defaults and env overrides."""
import os
import pytest
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
