"""Integration tests for observability features (telemetry, budgets, stream-json)."""

import json
import pytest
from tarbar_cli.telemetry import SessionTelemetry
from tarbar_cli.main import _build_parser, _print_stream_response, PermissionState
import sys


class _FakeStreamClient:
    def stream_chat(self, payload):
        yield {"conversation_id": "conv_test"}
        yield {"content": "Hello "}
        yield {"content": "world"}
        yield {"done": True}


def test_parser_supports_max_turns_argument():
    """Test parser accepts --max-turns argument."""
    parser = _build_parser()
    args = parser.parse_args(["--max-turns", "5", "--print", "--prompt", "test"])
    assert args.max_turns == 5


def test_parser_supports_max_budget_argument():
    """Test parser accepts --max-budget-usd argument."""
    parser = _build_parser()
    args = parser.parse_args(["--max-budget-usd", "0.50", "--print", "--prompt", "test"])
    assert args.max_budget_usd == 0.50


def test_parser_supports_stream_json_flag():
    """Test parser accepts --stream-json flag."""
    parser = _build_parser()
    args = parser.parse_args(["--stream-json", "--print", "--prompt", "test"])
    assert args.stream_json is True


def test_parser_supports_output_format_flag():
    """Test parser accepts --output-format flag."""
    parser = _build_parser()
    args = parser.parse_args(["--output-format", "json", "--print", "--prompt", "test"])
    assert args.output_format == "json"


def test_parser_supports_telemetry_flag():
    """Test parser accepts --telemetry flag."""
    parser = _build_parser()
    args = parser.parse_args(["--telemetry", "--print", "--prompt", "test"])
    assert args.telemetry is True


def test_telemetry_initialization_with_budget_limits():
    """Test SessionTelemetry initialized with budget controls."""
    telemetry = SessionTelemetry(
        max_turns=10,
        max_budget_usd=1.0,
        permission_mode="strict"
    )
    assert telemetry.max_turns == 10
    assert telemetry.max_budget_usd == 1.0
    assert telemetry.permission_mode == "strict"


def test_telemetry_enforces_max_turns_during_session():
    """Test max turns limit is enforced during session."""
    telemetry = SessionTelemetry(max_turns=2)
    
    # Add first turn - should not exceed
    telemetry.add_turn(1, "msg1", "resp1", [])
    exceeded, _ = telemetry.check_budget_limits()
    assert exceeded is False
    
    # Add second turn - should exceed max (2 turns)
    telemetry.add_turn(2, "msg2", "resp2", [])
    exceeded, reason = telemetry.check_budget_limits()
    assert exceeded is True
    assert "Max turns" in reason


def test_telemetry_enforces_budget_during_session():
    """Test budget limit is enforced during session."""
    telemetry = SessionTelemetry(max_budget_usd=0.001)
    
    # Simulate high token output exceeding budget
    telemetry.total_output_tokens = 2_000_000  # $0.004 cost
    
    exceeded, reason = telemetry.check_budget_limits()
    assert exceeded is True
    assert "Budget limit" in reason


def test_telemetry_session_mode_tracking():
    """Test telemetry tracks session mode correctly."""
    telemetry_print = SessionTelemetry(mode="print")
    assert telemetry_print.mode == "print"
    
    telemetry_interactive = SessionTelemetry(mode="interactive")
    assert telemetry_interactive.mode == "interactive"


def test_telemetry_to_json_with_limits():
    """Test JSON serialization includes budget limit info."""
    telemetry = SessionTelemetry(
        max_turns=5,
        max_budget_usd=1.0,
        conversation_id="conv_test"
    )
    telemetry.add_turn(1, "test", "response", ["tool1"])
    
    data = telemetry.to_dict()
    assert data["max_turns"] == 5
    assert data["max_budget_usd"] == 1.0
    assert data["conversation_id"] == "conv_test"
    assert data["mode"] == "print"


def test_telemetry_summary_includes_budget_info():
    """Test summary text includes budget information."""
    telemetry = SessionTelemetry(max_turns=5, max_budget_usd=1.0)
    telemetry.add_turn(1, "test", "response", [])
    
    summary = telemetry.summary()
    assert "Summary" in summary
    assert "Turns: 1" in summary
    assert "Tool calls: 0" in summary


def test_parser_no_default_budget_values():
    """Test parser has no default values for budget arguments."""
    parser = _build_parser()
    args = parser.parse_args(["--print", "--prompt", "test"])
    assert args.max_turns is None
    assert args.max_budget_usd is None
    assert args.output_format is None
    assert args.stream_json is False
    assert args.telemetry is False


def test_json_output_format_emits_structured_result(capsys):
    """Test JSON output format emits a structured result envelope."""
    telemetry = SessionTelemetry()
    result = _print_stream_response(
        _FakeStreamClient(),
        {"message": "hello", "conversation_id": "conv_test"},
        permission_state=PermissionState(),
        allowed_directory=None,
        interactive=False,
        telemetry=telemetry,
        output_format="json",
    )

    assert result == "Hello world"
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["type"] == "result"
    assert payload["response"] == "Hello world"
    assert payload["conversation_id"] == "conv_test"
    assert len(payload["telemetry"]["turns"]) == 1
