"""Tests for LLMAdapter — thinking-block stripping, tool-call parsing."""
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from llm_adapter import LLMAdapter, ToolUse
from config import LLMConfig


@pytest.fixture
def adapter():
    return LLMAdapter(LLMConfig())


# ─── strip_thinking_blocks ─────────────────────────────────────────────────

def test_strip_gemma4_channel_block(adapter):
    text = "<|channel>thought\nsome reasoning\n<channel|>\nActual answer"
    assert adapter.strip_thinking_blocks(text) == "Actual answer"


def test_strip_legacy_think_tags(adapter):
    text = "<think>internal reasoning</think>\nAnswer"
    assert adapter.strip_thinking_blocks(text) == "Answer"


def test_strip_empty_channel_block(adapter):
    """Empty <|channel>thought<channel|> must be stripped (known Gemma 4 leak)."""
    text = "<|channel>thought\n<channel|>Response"
    result = adapter.strip_thinking_blocks(text)
    assert "<|channel>" not in result
    assert "Response" in result


def test_no_strip_when_no_blocks(adapter):
    text = "Plain response with no blocks"
    assert adapter.strip_thinking_blocks(text) == text


def test_strip_multiple_blocks(adapter):
    text = "<|channel>thought\nthink1\n<channel|>mid<|channel>thought\nthink2\n<channel|>end"
    result = adapter.strip_thinking_blocks(text)
    assert "<|channel>" not in result
    assert "mid" in result
    assert "end" in result


# ─── extract_tool_calls ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_openai_style_tool_call(adapter):
    completion = {
        "choices": [{
            "message": {
                "content": None,
                "tool_calls": [{
                    "id": "call_abc",
                    "function": {
                        "name": "read_text_file",
                        "arguments": '{"target_file_path": "main.py"}',
                    }
                }]
            }
        }]
    }
    calls = await adapter.extract_tool_calls(completion)
    assert len(calls) == 1
    assert calls[0].tool_name == "read_text_file"
    assert calls[0].tool_input == {"target_file_path": "main.py"}
    assert calls[0].id == "call_abc"


@pytest.mark.asyncio
async def test_extract_native_gemma4_tool_call(adapter):
    """Fallback parser for native Gemma 4 <|tool_call> tokens."""
    text = '<|tool_call>call:bash_exec{command:<|"|>echo hi<|"|>}<tool_call|>'
    completion = {
        "choices": [{"message": {"content": text, "tool_calls": None}}]
    }
    calls = await adapter.extract_tool_calls(completion)
    assert len(calls) == 1
    assert calls[0].tool_name == "bash_exec"
    assert calls[0].tool_input.get("command") == "echo hi"


@pytest.mark.asyncio
async def test_extract_no_tool_calls(adapter):
    completion = {
        "choices": [{"message": {"content": "Plain text response", "tool_calls": None}}]
    }
    calls = await adapter.extract_tool_calls(completion)
    assert calls == []


@pytest.mark.asyncio
async def test_thinking_stripped_before_native_parse(adapter):
    """Native tool calls inside a thinking block must NOT be extracted."""
    text = "<|channel>thought\n<|tool_call>call:should_not_be_called{}<tool_call|>\n<channel|>\n<|tool_call>call:real_tool{}<tool_call|>"
    completion = {
        "choices": [{"message": {"content": text, "tool_calls": None}}]
    }
    calls = await adapter.extract_tool_calls(completion)
    # Only the real_tool outside the thinking block
    assert len(calls) == 1
    assert calls[0].tool_name == "real_tool"
