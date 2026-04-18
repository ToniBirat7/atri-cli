from __future__ import annotations

import sys
import pytest

from tarbar_cli import main as cli_main


def test_build_payload_includes_optional_fields():
    payload = cli_main._build_payload(
        message="hello",
        conversation_id="conv_1",
        allowed_directory="/tmp",
    )
    assert payload["message"] == "hello"
    assert payload["conversation_id"] == "conv_1"
    assert payload["allowed_directory"] == "/tmp"


def test_parser_supports_permissions_check_subcommand():
    parser = cli_main._build_parser()
    args = parser.parse_args(
        [
            "permissions",
            "check",
            "--tool-call",
            "Bash(git push origin main)",
            "--ask",
            "Bash(git push*)",
        ]
    )
    assert args.command == "permissions"
    assert args.permissions_command == "check"
    assert args.tool_call.startswith("Bash(")


def test_parser_supports_permission_mode_flag():
    parser = cli_main._build_parser()
    args = parser.parse_args(["--permission-mode", "plan", "--prompt", "hello"])
    assert args.permission_mode == "plan"


def test_mode_command_updates_runtime_state(capsys):
    state = cli_main.PermissionState(mode="default")

    handled = cli_main._handle_interactive_local_command("/mode plan", state)
    assert handled is True
    assert state.mode == "plan"

    handled = cli_main._handle_interactive_local_command("/mode", state)
    assert handled is True
    out = capsys.readouterr().out
    assert "permission_mode=plan" in out


def test_help_command_outputs_interactive_help(capsys):
    state = cli_main.PermissionState(mode="default")
    handled = cli_main._handle_interactive_local_command("/help", state)
    assert handled is True
    out = capsys.readouterr().out
    assert "Commands:" in out
    assert "/mode" in out
    assert "/timeline" in out


def test_print_turn_card_outputs_mode_and_turn(capsys):
    cli_main._print_turn_card(3, "plan")
    out = capsys.readouterr().out
    assert "turn 3" in out
    assert "mode=plan" in out


def test_main_prompt_convenience_mode_dispatches_print(monkeypatch):
    captured = {}

    class _FakeClient:
        def __init__(self, base_url: str, api_key=None):
            self.base_url = base_url
            self.api_key = api_key

    def _fake_run_print_mode(client, prompt, conversation_id, allowed_directory, permission_state, telemetry=None, output_format="text", stream_json=False):
        captured["prompt"] = prompt
        captured["conversation_id"] = conversation_id
        captured["allowed_directory"] = allowed_directory
        captured["permission_mode"] = permission_state.mode
        captured["output_format"] = output_format

    monkeypatch.setattr(cli_main, "OrchestratorClient", _FakeClient)
    monkeypatch.setattr(cli_main, "_run_print_mode", _fake_run_print_mode)

    monkeypatch.setattr(sys, "argv", ["tarbar", "Explain", "this", "repo"])  # tarbar "Explain this repo"
    cli_main.main()

    assert captured["prompt"] == "Explain this repo"
    assert captured["permission_mode"] == "default"


def test_main_handles_runtime_error_with_clean_exit(monkeypatch, capsys):
    class _FakeClient:
        def __init__(self, base_url: str, api_key=None):
            self.base_url = base_url
            self.api_key = api_key

    def _fake_run_print_mode(*args, **kwargs):
        raise RuntimeError("backend unavailable")

    monkeypatch.setattr(cli_main, "OrchestratorClient", _FakeClient)
    monkeypatch.setattr(cli_main, "_run_print_mode", _fake_run_print_mode)
    monkeypatch.setattr(sys, "argv", ["tarbar", "--print", "--prompt", "hello"])

    with pytest.raises(SystemExit) as exc_info:
        cli_main.main()

    assert exc_info.value.code == 1
    stderr = capsys.readouterr().err
    assert "backend unavailable" in stderr


def test_parser_supports_mcp_commands():
    parser = cli_main._build_parser()
    
    # Test mcp tools command
    args = parser.parse_args(["mcp", "tools"])
    assert args.command == "mcp"
    assert args.mcp_command == "tools"
    
    # Test mcp status command
    args = parser.parse_args(["mcp", "status"])
    assert args.command == "mcp"
    assert args.mcp_command == "status"
    
    # Test mcp refresh command
    args = parser.parse_args(["mcp", "refresh"])
    assert args.command == "mcp"
    assert args.mcp_command == "refresh"
    
    # Test mcp reconnect command
    args = parser.parse_args(["mcp", "reconnect", "filesystem"])
    assert args.command == "mcp"
    assert args.mcp_command == "reconnect"
    assert args.server == "filesystem"
    
    # Test mcp deferred command
    args = parser.parse_args(["mcp", "deferred", "shell", "--enable"])
    assert args.command == "mcp"
    assert args.mcp_command == "deferred"
    assert args.server == "shell"
    assert args.enable is True


def test_parser_supports_worktree_commands():
    parser = cli_main._build_parser()
    
    # Test worktree list command
    args = parser.parse_args(["worktrees", "list"])
    assert args.command == "worktrees"
    assert args.worktrees_command == "list"
    
    # Test worktree clean command
    args = parser.parse_args(["worktrees", "clean"])
    assert args.command == "worktrees"
    assert args.worktrees_command == "clean"


def test_parser_supports_timeline_verbosity_flag():
    parser = cli_main._build_parser()
    args = parser.parse_args(["--timeline-verbosity", "debug", "--print", "--prompt", "hello"])
    assert args.timeline_verbosity == "debug"


def test_timeline_command_updates_runtime_state(capsys):
    state = cli_main.PermissionState(mode="default")

    handled = cli_main._handle_interactive_local_command("/timeline minimal", state)
    assert handled is True

    handled = cli_main._handle_interactive_local_command("/timeline", state)
    assert handled is True
    out = capsys.readouterr().out
    assert "timeline_verbosity=minimal" in out

