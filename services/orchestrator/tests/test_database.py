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

    fetched = await database.get_conversation("conv_1")
    assert fetched is not None
    assert fetched.conversation_id == "conv_1"

    turns = await database.list_turns("conv_1")
    assert len(turns) == 1
    assert turns[0].user_message == "hello"

    history = await database.build_chat_history_messages("conv_1")
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_database_forks_conversation(tmp_path):
    db_path = tmp_path / "orchestrator.db"
    database = OrchestratorDatabase(f"sqlite:///{db_path}", enabled=True)
    await database.initialize()

    await database.ensure_conversation("conv_src", "general-purpose")
    await database.record_turn(
        conversation_id="conv_src",
        request_id="req_1",
        turn_index=1,
        user_message="hello",
        assistant_response="hi",
        status="completed",
        total_tool_calls=0,
        model="test-model",
        system_prompt="system prompt",
        turn_history=[],
        tool_events=[],
    )

    created = await database.fork_conversation("conv_src", "conv_dst")
    assert created is True

    destination = await database.get_conversation("conv_dst")
    assert destination is not None

    turns = await database.list_turns("conv_dst")
    assert len(turns) == 1
    assert turns[0].assistant_response == "hi"
