"""Tests for telemetry tracking."""

import pytest
from tarbar_cli.telemetry import SessionTelemetry, TurnMetrics
import json


def test_session_telemetry_initialization():
    """Test SessionTelemetry initialization."""
    telemetry = SessionTelemetry()
    assert telemetry.total_turns == 0
    assert telemetry.total_tool_calls == 0
    assert len(telemetry.unique_tools) == 0
    assert telemetry.session_duration_seconds >= 0


def test_add_turn_records_metrics():
    """Test adding a turn records correct metrics."""
    telemetry = SessionTelemetry()
    telemetry.add_turn(
        turn_number=1,
        user_message="test input",
        assistant_response="test output",
        tool_calls=["git_status", "cat_file"],
        duration_seconds=1.5,
    )
    
    assert telemetry.total_turns == 1
    assert telemetry.total_tool_calls == 2
    assert len(telemetry.unique_tools) == 2
    assert telemetry.total_input_chars == 10  # "test input"
    assert telemetry.total_output_chars == 11  # "test output"
    assert telemetry.avg_turn_duration == 1.5


def test_unique_tools_deduplication():
    """Test that unique tools are tracked correctly."""
    telemetry = SessionTelemetry()
    telemetry.add_turn(1, "msg1", "resp1", ["git_status", "git_push"])
    telemetry.add_turn(2, "msg2", "resp2", ["git_status", "cat_file"])
    
    assert len(telemetry.unique_tools) == 3
    assert telemetry.unique_tools == {"git_status", "git_push", "cat_file"}


def test_check_max_turns_limit():
    """Test max turns budget limit."""
    telemetry = SessionTelemetry(max_turns=2)
    
    # First turn should not exceed
    telemetry.add_turn(1, "msg1", "resp1", [])
    exceeded, reason = telemetry.check_budget_limits()
    assert exceeded is False
    
    # Second turn should not exceed (at limit)
    telemetry.add_turn(2, "msg2", "resp2", [])
    exceeded, reason = telemetry.check_budget_limits()
    assert exceeded is True
    assert "Max turns limit" in reason


def test_check_budget_usd_limit():
    """Test budget USD limit."""
    telemetry = SessionTelemetry(max_budget_usd=0.001)  # Very small budget
    
    # Simulate output tokens that would exceed budget
    telemetry.total_output_tokens = 1_000_000  # 1M tokens = $0.002 cost
    
    exceeded, reason = telemetry.check_budget_limits()
    assert exceeded is True
    assert "Budget limit" in reason


def test_telemetry_to_dict():
    """Test serialization to dictionary."""
    telemetry = SessionTelemetry(conversation_id="conv_123")
    telemetry.add_turn(1, "input", "output", ["tool1"])
    
    data = telemetry.to_dict()
    assert data["conversation_id"] == "conv_123"
    assert len(data["turns"]) == 1
    assert data["total_tool_calls"] == 1
    assert "tool1" in data["unique_tools"]


def test_telemetry_to_json():
    """Test serialization to JSON."""
    telemetry = SessionTelemetry(conversation_id="conv_123")
    telemetry.add_turn(1, "input", "output", ["tool1"])
    
    json_str = telemetry.to_json()
    data = json.loads(json_str)
    
    assert data["conversation_id"] == "conv_123"
    assert len(data["turns"]) == 1
    assert data["turns"][0]["tool_calls_count"] == 1


def test_telemetry_summary():
    """Test human-readable summary."""
    telemetry = SessionTelemetry()
    telemetry.add_turn(1, "input", "output", ["tool1"])
    
    summary = telemetry.summary()
    assert "Session Summary" in summary
    assert "Turns: 1" in summary
    assert "Tool calls: 1" in summary


def test_telemetry_summary_with_warnings():
    """Test summary includes warnings for exceeded limits."""
    telemetry = SessionTelemetry(max_turns=1)
    telemetry.add_turn(1, "input", "output", [])
    telemetry.check_budget_limits()
    
    summary = telemetry.summary()
    assert "Max turns limit exceeded" in summary


def test_avg_turn_duration_empty():
    """Test average turn duration with no turns."""
    telemetry = SessionTelemetry()
    assert telemetry.avg_turn_duration == 0.0


def test_avg_turn_duration_multiple_turns():
    """Test average turn duration with multiple turns."""
    telemetry = SessionTelemetry()
    telemetry.add_turn(1, "input1", "output1", [], duration_seconds=1.0)
    telemetry.add_turn(2, "input2", "output2", [], duration_seconds=3.0)
    
    assert telemetry.avg_turn_duration == 2.0
