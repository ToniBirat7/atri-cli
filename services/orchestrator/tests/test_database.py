"""Tests for orchestrator persistence."""

from __future__ import annotations

import pytest

from database import OrchestratorDatabase


@pytest.mark.asyncio
async def test_database_records_conversation_and_turn(tmp_path):
    db_path = tmp_path / "orchestrator.db"
    database = OrchestratorDatabase(f"sqlite:///{db_path}", enabled=True)
    await database.initialize()

    await database.ensure_conversation("conv_1", "general-purpose")
    await database.record_turn(
        conversation_id="conv_1",
        request_id="req_1",
        turn_index=2,
        user_message="hello",
        assistant_response="hi",
        status="completed",
        total_tool_calls=3,
        model="test-model",
        system_prompt="system prompt",
        turn_history=[
            {
                "turn_number": 1,
                "outcome": "tool_calls",
                "tool_calls_executed": 2,
                "metadata": {"tool_events": [{"tool_name": "read_file", "status": "ok"}]},
            }
        ],
        tool_events=[{"tool_name": "read_file", "status": "ok", "input": {"path": "/tmp/a"}}],
    )

    conversations = await database.list_conversations()
    assert len(conversations) == 1
    assert conversations[0].conversation_id == "conv_1"
    assert conversations[0].prompt_profile == "general-purpose"
