from __future__ import annotations

import sys

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


def test_main_prompt_convenience_mode_dispatches_print(monkeypatch):
    captured = {}

    class _FakeClient:
        def __init__(self, base_url: str, api_key=None):
            self.base_url = base_url
            self.api_key = api_key

    def _fake_run_print_mode(client, prompt, conversation_id, allowed_directory):
        captured["prompt"] = prompt
        captured["conversation_id"] = conversation_id
        captured["allowed_directory"] = allowed_directory

    monkeypatch.setattr(cli_main, "OrchestratorClient", _FakeClient)
    monkeypatch.setattr(cli_main, "_run_print_mode", _fake_run_print_mode)

    monkeypatch.setattr(sys, "argv", ["tarbar", "Explain", "this", "repo"])  # tarbar "Explain this repo"
    cli_main.main()

    assert captured["prompt"] == "Explain this repo"
