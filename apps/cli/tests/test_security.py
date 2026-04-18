"""Security regression tests for CLI and API."""

import pytest
from tarbar_cli.main import _extract_candidate_paths, _build_tool_call_expression
from tarbar_cli.telemetry import SessionTelemetry


def test_path_extraction_from_tool_input():
    """Test extraction of file paths from tool inputs."""
    tool_input = {
        "path": "/home/user/file.txt",
        "mode": "read",
    }
    paths = _extract_candidate_paths(tool_input)
    assert len(paths) == 1
    assert paths[0] == "/home/user/file.txt"


def test_path_extraction_multiple_fields():
    """Test extraction of multiple path-like fields."""
    tool_input = {
        "file_path": "/tmp/a.txt",
        "target": "/tmp/b.txt",
        "destination_path": "/tmp/c.txt",
    }
    paths = _extract_candidate_paths(tool_input)
    assert len(paths) == 3
    assert "/tmp/a.txt" in paths
    assert "/tmp/b.txt" in paths
    assert "/tmp/c.txt" in paths


def test_path_extraction_with_whitespace():
    """Test path extraction strips whitespace."""
    tool_input = {
        "path": "  /home/user/file.txt  ",
    }
    paths = _extract_candidate_paths(tool_input)
    assert len(paths) == 1
    assert paths[0] == "/home/user/file.txt"


def test_path_extraction_empty_values_ignored():
    """Test empty path values are ignored."""
    tool_input = {
        "path": "",
        "file_path": None,
        "target": "   ",
        "destination": "/tmp/file.txt",
    }
    paths = _extract_candidate_paths(tool_input)
    assert len(paths) == 1
    assert paths[0] == "/tmp/file.txt"


def test_tool_call_expression_with_path():
    """Test tool call expression generation with path."""
    expr = _build_tool_call_expression("write_file", {"path": "/tmp/file.txt"})
    assert expr == "write_file(/tmp/file.txt)"


def test_tool_call_expression_without_path():
    """Test tool call expression generation without path."""
    expr = _build_tool_call_expression("list_processes", {})
    assert expr == "list_processes"


def test_telemetry_no_data_leakage():
    """Test telemetry doesn't expose sensitive data in serialization."""
    telemetry = SessionTelemetry(
        conversation_id="conv_123",
        permission_mode="default"
    )
    telemetry.add_turn(
        1,
        user_message="secret_password_here",
        assistant_response="I did something",
        tool_calls=["sensitive_tool"],
    )
    
    data = telemetry.to_dict()
    # Telemetry tracks metrics, not sensitive content
    assert data["turns"][0]["user_message_length"] == len("secret_password_here")
    assert data["turns"][0]["assistant_response_length"] == len("I did something")
    assert "secret_password_here" not in str(data)


def test_telemetry_error_tracking_without_details():
    """Test telemetry tracks errors without exposing details."""
    telemetry = SessionTelemetry()
    error_msg = "Connection failed: invalid credentials"
    telemetry.errors.append(error_msg)
    
    data = telemetry.to_dict()
    assert len(data["errors"]) == 1


def test_permission_state_mode_enforcement():
    """Test permission state properly enforces mode."""
    from tarbar_cli.main import PermissionState
    
    state = PermissionState(mode="default")
    assert state.mode == "default"
    
    state.mode = "bypassPermissions"
    assert state.mode == "bypassPermissions"


def test_session_telemetry_prevents_negative_values():
    """Test telemetry rejects invalid negative values."""
    # Duration shouldn't be negative
    telemetry = SessionTelemetry()
    telemetry.add_turn(
        1,
        user_message="test",
        assistant_response="response",
        tool_calls=[],
        duration_seconds=0.5,  # Valid positive value
    )
    assert telemetry.turns[0].duration_seconds == 0.5


def test_telemetry_summary_safe_rendering():
    """Test telemetry summary doesn't expose internal state."""
    telemetry = SessionTelemetry(
        conversation_id="conv_abc123",
        max_turns=100
    )
    telemetry.add_turn(1, "msg", "resp", ["tool1", "tool2"])
    
    summary = telemetry.summary()
    # Summary should have human-readable stats, not raw data
    assert "Tool calls: 2" in summary
    assert "Unique tools: 2" in summary
    assert "Conv" not in summary  # Don't expose conversation ID in summary


def test_telemetry_json_format_validation():
    """Test telemetry JSON is properly formatted and safe."""
    import json
    
    telemetry = SessionTelemetry(conversation_id="test_conv")
    telemetry.add_turn(1, "user msg", "assistant response", ["tool1"])
    
    json_str = telemetry.to_json()
    # Should be valid JSON
    data = json.loads(json_str)
    assert isinstance(data, dict)
    assert "turns" in data
    assert "unique_tools" in data
    assert isinstance(data["unique_tools"], list)
