"""Tests for AgentLoop thinking_mode and turn logic."""
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agent_loop import AgentLoop


def test_thinking_for_turn_off():
    loop = AgentLoop(thinking_mode="off")
    assert loop._thinking_for_turn(has_tools=True) is False
    assert loop._thinking_for_turn(has_tools=False) is False


def test_thinking_for_turn_always():
    loop = AgentLoop(thinking_mode="always")
    assert loop._thinking_for_turn(has_tools=True) is True
    assert loop._thinking_for_turn(has_tools=False) is True


def test_thinking_for_turn_tool_calls_off():
    loop = AgentLoop(thinking_mode="tool_calls_off")
    assert loop._thinking_for_turn(has_tools=True) is False   # no thinking during tool use
    assert loop._thinking_for_turn(has_tools=False) is True   # think on final answer


def test_legacy_enable_thinking_compat():
    """enable_thinking=True must map to thinking_mode='always'."""
    loop = AgentLoop(enable_thinking=True)
    assert loop.thinking_mode == "always"


def test_max_turns_default():
    loop = AgentLoop()
    assert loop.max_turns == 10


def test_max_tool_calls_default():
    loop = AgentLoop()
    assert loop.max_tool_calls_per_turn == 3


def test_system_prompt_no_think_token():
    """_build_system_prompt must not inject <|think|> — that's the template's job."""
    loop = AgentLoop(thinking_mode="always")
    prompt = loop._build_system_prompt()
    assert "<|think|>" not in prompt
