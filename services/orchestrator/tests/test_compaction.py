"""
Tests for services/orchestrator/compaction.py
"""
import sys
from pathlib import Path
import pytest
import pytest_asyncio

_ORCH_DIR = Path(__file__).resolve().parent.parent
if str(_ORCH_DIR) not in sys.path:
    sys.path.insert(0, str(_ORCH_DIR))

from compaction import should_compact, compact_messages, COMPACTION_THRESHOLD


# ── should_compact ──────────────────────────────────────────────────────────────

class TestShouldCompact:
    def test_below_threshold_returns_false(self):
        ctx_size = 16384
        prompt_tokens = int(ctx_size * (COMPACTION_THRESHOLD - 0.05))
        assert should_compact(prompt_tokens, ctx_size) is False

    def test_at_threshold_returns_true(self):
        import math
        ctx_size = 16384
        # Use ceiling to land exactly at or above the threshold boundary (int() truncates)
        prompt_tokens = math.ceil(ctx_size * COMPACTION_THRESHOLD)
        assert should_compact(prompt_tokens, ctx_size) is True

    def test_above_threshold_returns_true(self):
        ctx_size = 8192
        prompt_tokens = ctx_size  # 100% used
        assert should_compact(prompt_tokens, ctx_size) is True

    def test_zero_ctx_size_returns_false(self):
        assert should_compact(9999, 0) is False

    def test_zero_tokens_returns_false(self):
        assert should_compact(0, 16384) is False


# ── compact_messages ────────────────────────────────────────────────────────────

class FakeLLMAdapter:
    """Minimal stub that returns a canned summary without hitting a real server."""

    def __init__(self, summary: str = "Summary of prior conversation."):
        self._summary = summary

    async def chat_completion(self, messages, tools=None, temperature=None, enable_thinking=False):
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": self._summary,
                        "tool_calls": None,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
        }


def _make_messages(n_turns: int = 15) -> list[dict]:
    msgs = [{"role": "system", "content": "You are a helpful assistant."}]
    for i in range(n_turns):
        msgs.append({"role": "user", "content": f"User turn {i}"})
        msgs.append({"role": "assistant", "content": f"Assistant turn {i}"})
    return msgs


@pytest.mark.asyncio
async def test_compact_preserves_system_message():
    messages = _make_messages(15)
    adapter = FakeLLMAdapter()
    result = await compact_messages(messages, adapter, ctx_size=16384)
    assert result[0]["role"] == "system"


@pytest.mark.asyncio
async def test_compact_returns_fewer_messages():
    messages = _make_messages(15)
    adapter = FakeLLMAdapter()
    result = await compact_messages(messages, adapter, ctx_size=16384)
    assert len(result) < len(messages)


@pytest.mark.asyncio
async def test_compact_summary_injected():
    summary_text = "Test summary XYZ"
    messages = _make_messages(15)
    adapter = FakeLLMAdapter(summary=summary_text)
    result = await compact_messages(messages, adapter, ctx_size=16384)
    all_content = " ".join(str(m.get("content", "")) for m in result)
    assert summary_text in all_content


@pytest.mark.asyncio
async def test_compact_preserves_tool_result_entries():
    """tool-role messages in the recent window are kept intact."""
    messages = _make_messages(12)
    messages.append({
        "role": "tool",
        "name": "read_text_file",
        "content": "file content here",
    })
    adapter = FakeLLMAdapter()
    result = await compact_messages(messages, adapter, ctx_size=16384)
    tool_msgs = [m for m in result if m.get("role") == "tool"]
    assert tool_msgs, "tool result entries should be preserved in the recent window"


@pytest.mark.asyncio
async def test_compact_short_messages_unchanged():
    """With 4 or fewer messages compaction should be skipped."""
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    adapter = FakeLLMAdapter()
    result = await compact_messages(messages, adapter, ctx_size=16384)
    assert result is messages  # identity: returned as-is
