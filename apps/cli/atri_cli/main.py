from __future__ import annotations

"""
Atri Code CLI - The main entry point for the local agentic coding assistant.

This module handles:
- Command-line argument parsing
- Interactive TUI lifecycle
- Background service management (start/stop/doctor)
- Session and history management
- MCP tool discovery and configuration
"""

import argparse
import os
import signal
import sys
import json
import time
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
import tempfile
from typing import Any, Optional

from .client import OrchestratorClient
from .telemetry import SessionTelemetry
from .tui import DashboardFrame, TUIRenderer, TIMELINE_VERBOSITY_LEVELS, TurnStatus
from .rich_tui import RichTUI
from .service_manager import ServiceManager

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.document import Document
    from prompt_toolkit.formatted_text import AnyFormattedText
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.styles import Style

    PROMPT_TOOLKIT_AVAILABLE = True
except Exception:
    PROMPT_TOOLKIT_AVAILABLE = False


PERMISSION_MODES = {
    "default",
    "plan",
    "dontAsk",
    "bypassPermissions",
    "acceptEdits",
    "review",
}

WRITE_LIKE_TOOLS = {
    "write_file",
    "edit_file",
    "delete_file",
    "rename_file",
    "move_file",
    "create_file",
    "set_allowed_directory",
}

PATH_INPUT_KEYS = {
    "path",
    "file_path",
    "target",
    "target_path",
    "destination",
    "destination_path",
    "new_path",
}


_TUI = TUIRenderer()
_RICH = RichTUI()

SLASH_COMMAND_DESCRIPTIONS: dict[str, str] = {
    "/help": "Show interactive command help",
    "/mode": "Show or set permission mode",
    "/compact": "Toggle compact output mode",
    "/model": "Show model and hardware info",
    "/cost": "Show session token usage",
    "/clear": "Clear terminal screen",
    "/timeline": "Show or set timeline verbosity",
    "/exit": "Exit interactive mode",
    "/quit": "Exit interactive mode",
}


def _env_first(*names: str, default: Optional[str] = None) -> Optional[str]:
    for name in names:
        value = os.getenv(name)
        if value is not None and value != "":
            return value
    return default


@dataclass
class PermissionState:
    mode: str = "default"
    allow: list[str] = field(default_factory=list)
    ask: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)
    prompted_write_targets: set[str] = field(default_factory=set)


def _supports_color() -> bool:
    return _TUI.supports_color()


def _style(text: str, *, color: Optional[str] = None, bold: bool = False, dim: bool = False) -> str:
    return _TUI.style(text, color=color, bold=bold, dim=dim)


def _print_info(message: str) -> None:
    _TUI.print_info(message)


def _print_success(message: str) -> None:
    _TUI.print_success(message)


def _print_warning(message: str) -> None:
    _TUI.print_warning(message)


def _print_error(message: str) -> None:
    _TUI.print_error(message)


def _emit_error(output_format: str, message: str) -> None:
    if output_format in {"json", "stream-json"}:
        print(json.dumps({"type": "error", "message": message}))
    else:
        _print_error(message)


def _interactive_help_text() -> str:
    # Use Rich help if available
    if RichTUI.is_available():
        _RICH.render_help()
        return ""
    return (
        "Commands:\n"
        "  /help               Show this help\n"
        "  /mode               Show current permission mode\n"
        "  /mode <name>        Set permission mode\n"
        "  /compact            Toggle compact output mode\n"
        "  /model              Show model and hardware info\n"
        "  /cost               Show session token usage\n"
        "  /clear              Clear terminal screen\n"
        "  /timeline           Show timeline verbosity\n"
        "  /timeline <level>   Set timeline verbosity (minimal/normal/debug)\n"
        "  /exit | /quit       Exit interactive mode\n"
        "\nKeyboard:\n"
        "  Tab                 Slash command autocomplete\n"
        "  Ctrl-R              History search\n"
        "  Ctrl-N              Insert newline while composing"
    )


def _fullscreen_tui_enabled() -> bool:
    flag = _env_first("ATRI_FULLSCREEN_TUI", "TARBAR_FULLSCREEN_TUI")
    if flag is not None:
        return flag.strip().lower() not in {"0", "false", "no", "off"}
    # Default to False for Claude Code-like scrolling experience
    return False


def _reduced_motion_enabled() -> bool:
    flag = _env_first("ATRI_REDUCED_MOTION", "TARBAR_REDUCED_MOTION")
    if flag is None:
        return False
    return flag.strip().lower() in {"1", "true", "yes", "on"}


def _preview_line(text: str, limit: int = 110) -> str:
    flattened = " ".join(text.split())
    if len(flattened) <= limit:
        return flattened
    return flattened[: max(0, limit - 3)] + "..."


def _append_bounded(lines: list[str], entry: str, limit: int) -> None:
    lines.append(entry)
    if len(lines) > limit:
        del lines[: len(lines) - limit]


def _render_interactive_dashboard(
    *,
    conversation_id: Optional[str],
    permission_state: PermissionState,
    status: Optional[TurnStatus],
    conversation_log: list[str],
    tool_log: list[str],
    note: str,
    reduced_motion: bool,
) -> None:
    subtitle = note
    if conversation_id:
        subtitle = f"{subtitle} | conversation {conversation_id}"

    _TUI.render_fullscreen_dashboard(
        DashboardFrame(
            title="Atri Code CLI",
            subtitle=subtitle,
            mode=permission_state.mode,
            status=status,
            conversation=conversation_log[-12:],
            tool_events=tool_log[-10:],
            command_hints=[
                "/help, /mode, /timeline, /exit",
                "Tab completes slash commands",
                "Ctrl-N inserts a newline in multiline input",
            ],
            footer=[
                "Tab: complete | Ctrl-R: history search | Ctrl-N: newline | Enter: submit",
                f"timeline={_TUI.timeline_verbosity} | reduced_motion={'on' if reduced_motion else 'off'}",
            ],
            reduced_motion=reduced_motion,
        )
    )


if PROMPT_TOOLKIT_AVAILABLE:
    class _SlashCompleter(Completer):
        """Autocomplete slash commands and known argument values."""

        def get_completions(self, document: Document, complete_event):
            text = document.text_before_cursor
            if not text.startswith("/"):
                return

            stripped = text.lstrip()
            parts = stripped.split()

            if len(parts) <= 1 and not stripped.endswith(" "):
                for command, description in sorted(SLASH_COMMAND_DESCRIPTIONS.items()):
                    if command.startswith(stripped):
                        yield Completion(
                            command,
                            start_position=-len(stripped),
                            display_meta=description,
                        )
                return

            base_command = parts[0] if parts else stripped
            if base_command == "/mode" and stripped.startswith("/mode "):
                suffix = stripped[len("/mode "):]
                for mode in sorted(PERMISSION_MODES):
                    if mode.startswith(suffix):
                        yield Completion(
                            mode,
                            start_position=-len(suffix),
                            display_meta="Permission mode",
                        )
                return

            if base_command == "/timeline" and stripped.startswith("/timeline "):
                suffix = stripped[len("/timeline "):]
                for level in TIMELINE_VERBOSITY_LEVELS:
                    if level.startswith(suffix):
                        yield Completion(
                            level,
                            start_position=-len(suffix),
                            display_meta="Timeline verbosity",
                        )


def _slash_hint_for_input(text: str) -> Optional[str]:
    stripped = (text or "").strip()
    if not stripped.startswith("/"):
        return None

    parts = stripped.split()
    command = parts[0]

    if command in {"/mode", "/timeline"} and len(parts) > 1:
        value = parts[1]
        if command == "/mode":
            if value not in PERMISSION_MODES:
                return f"unknown mode '{value}' | valid: {', '.join(sorted(PERMISSION_MODES))}"
            return f"set permission mode -> {value}"
        if command == "/timeline":
            if value not in TIMELINE_VERBOSITY_LEVELS:
                return (
                    f"unknown timeline level '{value}' | "
                    f"valid: {', '.join(TIMELINE_VERBOSITY_LEVELS)}"
                )
            return f"set timeline verbosity -> {value}"

    if command in SLASH_COMMAND_DESCRIPTIONS:
        return SLASH_COMMAND_DESCRIPTIONS[command]

    candidates = [name for name in sorted(SLASH_COMMAND_DESCRIPTIONS) if name.startswith(command)]
    if candidates:
        return f"matching: {', '.join(candidates)}"
    return f"unknown command '{command}' | try /help"


def _build_prompt_toolkit_session() -> Optional[Any]:
    if not PROMPT_TOOLKIT_AVAILABLE:
        return None

    history_path = Path.home() / ".local" / "share" / "atri-code-cli" / "history"
    history_path.parent.mkdir(parents=True, exist_ok=True)

    key_bindings = KeyBindings()

    @key_bindings.add("c-n")
    def _(event):
        event.app.current_buffer.insert_text("\n")

    return PromptSession(
        history=FileHistory(str(history_path)),
        auto_suggest=AutoSuggestFromHistory(),
        completer=_SlashCompleter() if PROMPT_TOOLKIT_AVAILABLE else None,
        complete_while_typing=True,
        key_bindings=key_bindings,
    )


def _prompt_toolkit_bottom_toolbar(permission_state: PermissionState, text: str) -> AnyFormattedText:
    hint = _slash_hint_for_input(text)
    left = f" mode={permission_state.mode} "
    if hint:
        return [
            ("class:toolbar", left),
            ("class:toolbar", "| "),
            ("class:toolbar", hint),
        ]
    return [("class:toolbar", left), ("class:toolbar", "| Tab complete | Ctrl-R history | Ctrl-N newline")]


def _read_interactive_input(
    session: Optional[Any],
    permission_state: PermissionState,
) -> Optional[str]:
    if session is None:
        try:
            return input(f"\n{_style(f'atri-cli[{permission_state.mode}]> ', color='cyan', bold=True)}").strip()
        except (KeyboardInterrupt, EOFError):
            return None

    try:
        user_input = session.prompt(
            f"atri-cli[{permission_state.mode}]> ",
            bottom_toolbar=lambda: _prompt_toolkit_bottom_toolbar(
                permission_state,
                session.default_buffer.document.text,
            ),
            style=_PTK_STYLE,
        )
        return user_input.strip()
    except (KeyboardInterrupt, EOFError):
        return None


if PROMPT_TOOLKIT_AVAILABLE:
    _PTK_STYLE = Style.from_dict({
        "toolbar": "bg:#1f2937 #d1d5db",
    })
else:
    _PTK_STYLE = {}


def _tui_enabled() -> bool:
    return _supports_color() and sys.stdout.isatty()


def _status_set(message: str) -> None:
    _TUI.status_set(
        TurnStatus(
            turn_number=0,
            elapsed_seconds=0.0,
            input_tokens=0,
            output_tokens=0,
            tool_calls=0,
            phase=message,
        )
    )


def _status_clear() -> None:
    _TUI.status_clear()


def _print_turn_card(turn_number: int, mode: str) -> None:
    _TUI.print_turn_card(turn_number, mode)


def _render_timeline_event(event: dict[str, Any], output_format: str, quiet: bool = False) -> None:
    if quiet:
        return
    if output_format == "text" and RichTUI.is_available():
        etype = event.get("type")
        if etype == "tool_call_start":
            _RICH.render_tool_call(event.get("tool_name", "tool"), event.get("tool_input", {}))
            return
        if etype == "tool_call_result":
            res = event.get("tool_result")
            if res is not None and not isinstance(res, str):
                res = json.dumps(res, indent=2)
            _RICH.render_tool_result(event.get("tool_name", "tool"), res or "", success=not event.get("is_error", False))
            return
    _TUI.render_timeline_event(event, output_format)


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    # Lightweight approximation used for live counters when provider usage is unavailable.
    return max(1, math.ceil(len(text) / 4))


def _update_live_status(
    turn_number: int,
    turn_start: float,
    input_tokens: int,
    output_chars: int,
    tool_calls: int,
    phase: str,
    output_tokens_exact: Optional[int] = None,
) -> None:
    if not _tui_enabled():
        return
    _TUI.status_set(
        TurnStatus(
            turn_number=turn_number,
            elapsed_seconds=max(0.0, time.time() - turn_start),
            input_tokens=input_tokens,
            output_tokens=(
                output_tokens_exact
                if output_tokens_exact is not None
                else max(0, math.ceil(output_chars / 4))
            ),
            tool_calls=tool_calls,
            phase=phase,
        )
    )


def _print_turn_status_summary(
    turn_number: int,
    turn_start: float,
    input_tokens: int,
    output_chars: int,
    tool_calls: int,
    phase: str,
    output_tokens_exact: Optional[int] = None,
) -> None:
    _TUI.print_status_summary(
        TurnStatus(
            turn_number=turn_number,
            elapsed_seconds=max(0.0, time.time() - turn_start),
            input_tokens=input_tokens,
            output_tokens=(
                output_tokens_exact
                if output_tokens_exact is not None
                else max(0, math.ceil(output_chars / 4))
            ),
            tool_calls=tool_calls,
            phase=phase,
        )
    )


def _build_payload(
    message: str,
    conversation_id: Optional[str],
    allowed_directory: Optional[str],
) -> dict:
    payload = {"message": message}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    if allowed_directory:
        payload["allowed_directory"] = allowed_directory
    return payload


def _extract_candidate_paths(tool_input: Any) -> list[str]:
    if not isinstance(tool_input, dict):
        return []

    paths: list[str] = []
    for key in PATH_INPUT_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            paths.append(value.strip())
    return paths


def _is_path_within_allowed_directory(path_str: str, allowed_directory: Optional[str]) -> bool:
    if not allowed_directory:
        return True

    try:
        root = Path(allowed_directory).expanduser().resolve()
        candidate = Path(path_str).expanduser().resolve()
        candidate.relative_to(root)
        return True
    except Exception:
        return False


def _build_tool_call_expression(tool_name: str, tool_input: Any) -> str:
    paths = _extract_candidate_paths(tool_input)
    if paths:
        return f"{tool_name}({paths[0]})"
    return tool_name


def _prompt_write_target(tool_name: str, target_path: str) -> bool:
    answer = input(
        f"\n[permission] {tool_name} wants to write outside allowed scope: {target_path}\n"
        "Allow similar writes for this path in this session? [y/N]: "
    ).strip().lower()
    return answer in {"y", "yes"}


def _handle_interactive_local_command(user_input: str, permission_state: PermissionState) -> bool:
    if user_input in {"/help", "/?"}:
        help_text = _interactive_help_text()
        if help_text:
            print(help_text)
        return True

    if user_input == "/mode":
        _RICH.render_info(
            f"permission_mode={permission_state.mode} "
            f"allow={len(permission_state.allow)} ask={len(permission_state.ask)} deny={len(permission_state.deny)}"
        )
        return True

    if user_input.startswith("/mode "):
        requested = user_input.split(None, 1)[1].strip()
        if requested not in PERMISSION_MODES:
            valid = ", ".join(sorted(PERMISSION_MODES))
            _RICH.render_warning(f"Unknown mode: {requested}. Valid modes: {valid}")
            return True
        permission_state.mode = requested
        _RICH.render_success(f"Permission mode set to {requested}")
        return True

    if user_input == "/compact":
        is_compact = _RICH.toggle_compact()
        _RICH.render_info(f"Compact mode {'enabled' if is_compact else 'disabled'}")
        return True

    if user_input == "/model":
        info = {
            "Model": "Gemma 4 E2B Instruct (Q4_K_M)",
            "Runtime": "llama.cpp",
            "Reasoning": "enabled",
        }
        # Try to load hardware config
        try:
            repo_root = Path(__file__).resolve().parents[3]
            config_path = repo_root / "runtime" / "llm" / "launch_config.json"
            if config_path.exists():
                hw = json.loads(config_path.read_text(encoding="utf-8"))
                info["GPU"] = hw.get("gpu_name", "unknown")
                info["VRAM"] = f"{hw.get('gpu_vram_mb', 0)} MB"
                info["Context"] = f"{hw.get('recommended_ctx_size', 0)} tokens"
                info["Flash Attn"] = "✓" if hw.get("flash_attn") else "✗"
                info["KV Cache"] = hw.get("kv_cache_type_k", "f16")
                info["Threads"] = str(hw.get("recommended_threads", "?"))
        except Exception:
            pass
        _RICH.render_model_info(info)
        return True

    if user_input == "/cost":
        # Access telemetry from the outer scope — this is handled by printing
        _RICH.render_info("Use --telemetry flag at startup or check session summary after exit.")
        return True

    if user_input == "/clear":
        _RICH.clear_screen()
        return True

    if user_input == "/timeline":
        _RICH.render_info(f"timeline_verbosity={_TUI.timeline_verbosity}")
        return True

    if user_input.startswith("/timeline "):
        requested = user_input.split(None, 1)[1].strip()
        if requested not in TIMELINE_VERBOSITY_LEVELS:
            valid = ", ".join(TIMELINE_VERBOSITY_LEVELS)
            _RICH.render_warning(f"Unknown timeline verbosity: {requested}. Valid levels: {valid}")
            return True
        _TUI.set_timeline_verbosity(requested)
        _RICH.render_success(f"Timeline verbosity set to {requested}")
        return True

    if user_input.startswith("/"):
        _RICH.render_warning(f"Unknown command: {user_input}. Type /help for available commands.")
        return True

    return False


def _render_permission_event(
    client: OrchestratorClient,
    event: dict[str, Any],
    permission_state: PermissionState,
    allowed_directory: Optional[str],
    interactive: bool,
    quiet: bool = False,
) -> None:
    if event.get("type") != "tool_call_start":
        return

    tool_name = str(event.get("tool_name") or "").strip()
    tool_input = event.get("tool_input", {})
    if not tool_name:
        return

    tool_call = _build_tool_call_expression(tool_name, tool_input)
    response = client.request_json(
        "POST",
        "/permissions/evaluate",
        {
            "tool_call": tool_call,
            "mode": permission_state.mode,
            "allow": permission_state.allow,
            "ask": permission_state.ask,
            "deny": permission_state.deny,
        },
    )
    if not quiet:
        print(f"\n[permission] {tool_call} -> {response.get('action')} ({response.get('reason')})")

    if tool_name not in WRITE_LIKE_TOOLS:
        return

    for target_path in _extract_candidate_paths(tool_input):
        key = f"{tool_name}:{target_path}"
        if key in permission_state.prompted_write_targets:
            continue
        permission_state.prompted_write_targets.add(key)

        if _is_path_within_allowed_directory(target_path, allowed_directory):
            continue

        if not quiet:
            print(f"[safety] Write target outside allowed directory: {target_path}")
        if interactive:
            allowed = _prompt_write_target(tool_name, target_path)
            if allowed:
                permission_state.allow.append(f"{tool_name}({target_path})")
                if not quiet:
                    print(f"[permission] Added allow rule for {tool_name}({target_path})")
            else:
                permission_state.deny.append(f"{tool_name}({target_path})")
                if not quiet:
                    print(f"[permission] Added deny rule for {tool_name}({target_path})")


def _print_stream_response(
    client: OrchestratorClient,
    payload: dict,
    permission_state: PermissionState,
    allowed_directory: Optional[str],
    interactive: bool,
    telemetry: Optional[SessionTelemetry] = None,
    output_format: str = "text",
    stream_json: bool = False,
) -> str:
    chunks: list[str] = []
    active_conversation_id = payload.get("conversation_id")
    turn_number = 1
    first_content_chunk = True
    turn_start = time.time()
    input_tokens = _estimate_tokens(str(payload.get("message", "")) )
    output_chars = 0
    tool_calls = 0
    tool_names: list[str] = []
    content_started = False
    exact_input_tokens = 0
    exact_output_tokens = 0
    has_exact_usage = False

    effective_output_format = "stream-json" if stream_json else output_format
    if effective_output_format == "text":
        _print_turn_card(turn_number, permission_state.mode)
        _update_live_status(turn_number, turn_start, input_tokens, output_chars, tool_calls, "thinking")
    for event in client.stream_chat(payload):
        if event.get("done"):
            break
        if "event" in event and isinstance(event["event"], dict):
            _render_timeline_event(event["event"], effective_output_format)
            event_type = str(event["event"].get("type") or "")
            if event_type == "usage":
                exact_input_tokens += int(event["event"].get("prompt_tokens") or 0)
                exact_output_tokens += int(event["event"].get("completion_tokens") or 0)
                has_exact_usage = True
                if not content_started:
                    _update_live_status(
                        turn_number,
                        turn_start,
                        exact_input_tokens,
                        output_chars,
                        tool_calls,
                        "thinking",
                        output_tokens_exact=exact_output_tokens,
                    )
                continue
            if event_type == "tool_call_start":
                tool_calls += 1
                tool_name = str(event["event"].get("tool_name") or "tool")
                tool_names.append(tool_name)
                if not content_started:
                    _update_live_status(
                        turn_number,
                        turn_start,
                        exact_input_tokens if has_exact_usage else input_tokens,
                        output_chars,
                        tool_calls,
                        "tool",
                        output_tokens_exact=exact_output_tokens if has_exact_usage else None,
                    )
            elif event_type == "turn_complete":
                if not content_started:
                    _update_live_status(
                        turn_number,
                        turn_start,
                        exact_input_tokens if has_exact_usage else input_tokens,
                        output_chars,
                        tool_calls,
                        "finalizing",
                        output_tokens_exact=exact_output_tokens if has_exact_usage else None,
                    )
            else:
                if not content_started:
                    _update_live_status(
                        turn_number,
                        turn_start,
                        exact_input_tokens if has_exact_usage else input_tokens,
                        output_chars,
                        tool_calls,
                        "thinking",
                        output_tokens_exact=exact_output_tokens if has_exact_usage else None,
                    )
            _render_permission_event(
                client,
                event["event"],
                permission_state,
                allowed_directory=allowed_directory,
                interactive=interactive,
            )
            
            if event_type == "plan_proposed":
                plan = event["event"].get("plan", {})
                goal = plan.get("goal", "Execute task")
                steps = plan.get("steps", [])
                _status_clear()
                _RICH.stop_thinking()
                approved = _RICH.render_plan(goal, steps)
                if approved:
                    return "PLAN_APPROVED"
                else:
                    return "PLAN_REJECTED"
            
            continue
        
        if "plan" in event:
            plan = event["plan"]
            goal = plan.get("goal", "Execute task")
            steps = plan.get("steps", [])
            _status_clear()
            _RICH.stop_thinking()
            approved = _RICH.render_plan(goal, steps)
            if approved:
                return "PLAN_APPROVED"
            else:
                return "PLAN_REJECTED"
        if "conversation_id" in event:
            active_conversation_id = event["conversation_id"]
            if telemetry:
                telemetry.conversation_id = active_conversation_id
            continue
        if "error" in event:
            _status_clear()
            if telemetry:
                telemetry.errors.append(event["error"])
            raise RuntimeError(event["error"])
        if "content" in event:
            text = event["content"]
            output_chars += len(text)
            if effective_output_format == "stream-json":
                print(json.dumps({"type": "content", "text": text}))
            elif effective_output_format == "text":
                _RICH.print_streaming_token(text, is_first=first_content_chunk)
                if first_content_chunk:
                    _status_clear()
                    content_started = True
                    first_content_chunk = False
            chunks.append(text)
            continue

    response_text = "".join(chunks)
    _status_clear()
    
    if effective_output_format == "text":
        _RICH.finish_streaming()
    turn_duration = time.time() - turn_start
    
    # Record telemetry
    if telemetry:
        user_message = payload.get("message", "")
        if has_exact_usage:
            telemetry.total_input_tokens += exact_input_tokens
            telemetry.total_output_tokens += exact_output_tokens
        else:
            telemetry.total_input_tokens += input_tokens
            telemetry.total_output_tokens += _estimate_tokens(response_text)
        telemetry.add_turn(
            turn_number=turn_number,
            user_message=user_message,
            assistant_response=response_text,
            tool_calls=tool_names,
            duration_seconds=turn_duration,
        )
        exceeded, reason = telemetry.check_budget_limits()
        if exceeded:
            if effective_output_format in {"stream-json", "json"}:
                print(json.dumps({"type": "error", "message": reason}))
            else:
                _print_error(reason)
            raise SystemExit(1)

    if effective_output_format == "json":
        result = {
            "type": "result",
            "response": response_text,
            "turn": turn_number,
        }
        if active_conversation_id:
            result["conversation_id"] = active_conversation_id
        if telemetry:
            result["telemetry"] = telemetry.to_dict()
        print(json.dumps(result))
    elif effective_output_format == "stream-json":
        if active_conversation_id:
            print(json.dumps({"type": "conversation_id", "conversation_id": active_conversation_id}))
    else:
        print()
        _print_turn_status_summary(
            turn_number,
            turn_start,
            exact_input_tokens if has_exact_usage else input_tokens,
            output_chars,
            tool_calls,
            "complete",
            output_tokens_exact=exact_output_tokens if has_exact_usage else None,
        )
        if active_conversation_id:
            _print_info(f"conversation_id: {active_conversation_id}")
    
    return response_text


def _run_print_mode(
    client: OrchestratorClient,
    prompt: str,
    conversation_id: Optional[str],
    allowed_directory: Optional[str],
    permission_state: PermissionState,
    telemetry: Optional[SessionTelemetry] = None,
    output_format: str = "text",
    stream_json: bool = False,
) -> None:
    payload = _build_payload(prompt, conversation_id, allowed_directory)
    _print_stream_response(
        client,
        payload,
        permission_state=permission_state,
        allowed_directory=allowed_directory,
        interactive=False,
        telemetry=telemetry,
        output_format=output_format,
        stream_json=stream_json,
    )


def _handle_diff_review(event: dict[str, Any]) -> tuple[str, Optional[str]]:
    """Handles the side-by-side diff review in VS Code."""
    review_data = event.get("review", {})
    path = review_data.get("path")
    before = review_data.get("before", "")
    after = review_data.get("after", "")
    
    _status_clear()
    _RICH.stop_thinking()
    
    _RICH.render_review_header(path)
    
    file_basename = os.path.basename(path)
    
    # Create temp files for comparison
    with tempfile.NamedTemporaryFile(mode='w', suffix=f'.original.{file_basename}', delete=False) as f_base:
        f_base.write(before)
        base_path = f_base.name
        
    with tempfile.NamedTemporaryFile(mode='w', suffix=f'.proposed.{file_basename}', delete=False) as f_head:
        f_head.write(after)
        head_path = f_head.name
        
    try:
        # Launch VS Code Diff
        subprocess.run(["code", "--wait", "--diff", base_path, head_path], check=False)
    except Exception:
        _print_warning("VS Code CLI ('code') not found or failed to launch. Falling back to terminal diff.")
        subprocess.run(["diff", "-u", base_path, head_path])
        
    try:
        prompt = _style(f"\nApply changes to {path}? ", color="cyan", bold=True)
        resp = input(f"{prompt}[y/N/e (manual edit)]: ").strip().lower()
        
        if resp == "y":
            with open(head_path, "r", encoding="utf-8") as f:
                final_content = f.read()
            return "EDIT_APPROVED", final_content
        elif resp == "e":
            _RICH.render_info("Opening proposed file for manual editing...")
            try:
                subprocess.run(["code", "--wait", head_path], check=False)
            except Exception:
                _print_error("Failed to re-open VS Code for manual edit.")
            with open(head_path, "r", encoding="utf-8") as f:
                final_content = f.read()
            return "EDIT_APPROVED", final_content
        else:
            return "EDIT_REJECTED", None
    finally:
        for p in [base_path, head_path]:
            if os.path.exists(p):
                os.remove(p)


def _run_interactive(
    client: OrchestratorClient,
    conversation_id: Optional[str],
    allowed_directory: Optional[str],
    permission_state: PermissionState,
    telemetry: Optional[SessionTelemetry] = None,
    output_format: str = "text",
    stream_json: bool = False,
) -> None:
    fullscreen_mode = _fullscreen_tui_enabled()
    reduced_motion = _reduced_motion_enabled()
    conversation_log: list[str] = []
    tool_log: list[str] = []
    current_status: Optional[TurnStatus] = None

    if fullscreen_mode:
        _render_interactive_dashboard(
            conversation_id=conversation_id,
            permission_state=permission_state,
            status=current_status,
            conversation_log=conversation_log,
            tool_log=tool_log,
            note="interactive mode",
            reduced_motion=reduced_motion,
        )
    else:
        _RICH.render_welcome(
            api_url=client.base_url,
            permission_mode=permission_state.mode,
            model="Gemma 4 E2B Instruct (Q4_K_M)",
            reasoning=True,
        )
        if conversation_id:
            _RICH.render_info(f"Resuming conversation: {conversation_id}")

    active_conversation_id = conversation_id
    turn_number = 0
    effective_output_format = "stream-json" if stream_json else output_format
    prompt_session = _build_prompt_toolkit_session()

    while True:
        if fullscreen_mode:
            _render_interactive_dashboard(
                conversation_id=active_conversation_id,
                permission_state=permission_state,
                status=current_status,
                conversation_log=conversation_log,
                tool_log=tool_log,
                note="waiting for input",
                reduced_motion=reduced_motion,
            )
        user_input = _read_interactive_input(prompt_session, permission_state)
        if user_input is None:
            print("\nExiting.")
            return

        if not user_input:
            continue
            
        if not fullscreen_mode:
            _RICH.render_user_message(user_input)
        if user_input in {"/exit", "/quit"}:
            _print_success("Goodbye.")
            return
        if _handle_interactive_local_command(user_input, permission_state):
            if fullscreen_mode:
                _render_interactive_dashboard(
                    conversation_id=active_conversation_id,
                    permission_state=permission_state,
                    status=current_status,
                    conversation_log=conversation_log,
                    tool_log=tool_log,
                    note=f"command handled: {user_input}",
                    reduced_motion=reduced_motion,
                )
            continue

        turn_number += 1
        turn_start = time.time()
        payload = _build_payload(user_input, active_conversation_id, allowed_directory)
        input_tokens = _estimate_tokens(user_input)
        output_chars = 0
        tool_calls = 0
        tool_names: list[str] = []
        content_started = False
        exact_input_tokens = 0
        exact_output_tokens = 0
        has_exact_usage = False
        current_status = TurnStatus(
            turn_number=turn_number,
            elapsed_seconds=0.0,
            input_tokens=input_tokens,
            output_tokens=0,
            tool_calls=tool_calls,
            phase="thinking",
        )
        if fullscreen_mode:
            _render_interactive_dashboard(
                conversation_id=active_conversation_id,
                permission_state=permission_state,
                status=current_status,
                conversation_log=conversation_log,
                tool_log=tool_log,
                note=f"turn {turn_number} started",
                reduced_motion=reduced_motion,
            )
        elif effective_output_format == "text":
            _print_turn_card(turn_number, permission_state.mode)
            _update_live_status(turn_number, turn_start, input_tokens, output_chars, tool_calls, "thinking")

        first_content_chunk = True
        chunks: list[str] = []
        while True: # Plan approval loop
            for event in client.stream_chat(payload):
                if event.get("done"):
                    break
                if "plan" in event:
                    plan = event["plan"]
                    goal = plan.get("goal", "Execute task")
                    steps = plan.get("steps", [])
                    _status_clear()
                    _RICH.stop_thinking()
                    approved = _RICH.render_plan(goal, steps)
                    if approved:
                        payload["message"] = "Plan approved. Proceed with execution."
                        break 
                    else:
                        _RICH.render_warning("Plan rejected. Returning to input.")
                        payload = None # Signal rejection
                        break
                
                if "event" in event and isinstance(event["event"], dict):
                    _render_timeline_event(event["event"], effective_output_format, quiet=fullscreen_mode)
                    event_type = str(event["event"].get("type") or "")
                    
                    if event_type == "turn_review_requested":
                        review_result, final_content = _handle_diff_review(event["event"])
                        if review_result == "EDIT_APPROVED":
                            # Actually apply to the REAL file now!
                            file_path = event["event"]["review"]["path"]
                            try:
                                with open(file_path, "w", encoding="utf-8") as f:
                                    f.write(final_content)
                                _print_success(f"Changes applied to {file_path}")
                                payload["message"] = f"Review approved and applied to {file_path}. Proceed."
                                break
                            except Exception as e:
                                _print_error(f"Failed to write to {file_path}: {e}")
                                payload = None
                                break
                        else:
                            _RICH.render_warning("Changes rejected.")
                            payload = None
                            break

                    if event_type == "usage":
                        exact_input_tokens += int(event["event"].get("prompt_tokens") or 0)
                        exact_output_tokens += int(event["event"].get("completion_tokens") or 0)
                        has_exact_usage = True
                        if not content_started and not fullscreen_mode:
                            _update_live_status(
                                turn_number,
                                turn_start,
                                exact_input_tokens,
                                output_chars,
                                tool_calls,
                                "thinking",
                                output_tokens_exact=exact_output_tokens,
                            )
                        continue
                    if event_type == "tool_call_start":
                        tool_calls += 1
                        tool_name = str(event["event"].get("tool_name") or "tool")
                        tool_names.append(tool_name)
                        if fullscreen_mode:
                            _append_bounded(tool_log, f"turn {turn_number}: tool started {tool_name}", 10)
                        if not content_started and not fullscreen_mode:
                            _update_live_status(
                                turn_number,
                                turn_start,
                                exact_input_tokens if has_exact_usage else input_tokens,
                                output_chars,
                                tool_calls,
                                "tool",
                                output_tokens_exact=exact_output_tokens if has_exact_usage else None,
                            )
                    elif event_type == "turn_complete":
                        if not content_started and not fullscreen_mode:
                            _update_live_status(
                                turn_number,
                                turn_start,
                                exact_input_tokens if has_exact_usage else input_tokens,
                                output_chars,
                                tool_calls,
                                "finalizing",
                                output_tokens_exact=exact_output_tokens if has_exact_usage else None,
                            )
                    else:
                        if not content_started and not fullscreen_mode:
                            _update_live_status(
                                turn_number,
                                turn_start,
                                exact_input_tokens if has_exact_usage else input_tokens,
                                output_chars,
                                tool_calls,
                                "thinking",
                                output_tokens_exact=exact_output_tokens if has_exact_usage else None,
                            )
                    _render_permission_event(
                        client,
                        event["event"],
                        permission_state,
                        allowed_directory=allowed_directory,
                        interactive=True,
                        quiet=fullscreen_mode,
                    )
                    continue
                if "conversation_id" in event:
                    active_conversation_id = event["conversation_id"]
                    if telemetry:
                        telemetry.conversation_id = active_conversation_id
                    continue
                if "error" in event:
                    _status_clear()
                    if telemetry:
                        telemetry.errors.append(event["error"])
                    _emit_error(effective_output_format, str(event["error"]))
                    if fullscreen_mode:
                        _append_bounded(tool_log, f"turn {turn_number}: error {event['error']}", 10)
                        current_status = TurnStatus(
                            turn_number=turn_number,
                            elapsed_seconds=max(0.0, time.time() - turn_start),
                            input_tokens=exact_input_tokens if has_exact_usage else input_tokens,
                            output_tokens=exact_output_tokens if has_exact_usage else _estimate_tokens("".join(chunks)),
                            tool_calls=tool_calls,
                            phase="error",
                        )
                        _render_interactive_dashboard(
                            conversation_id=active_conversation_id,
                            permission_state=permission_state,
                            status=current_status,
                            conversation_log=conversation_log,
                            tool_log=tool_log,
                            note=f"turn {turn_number} failed",
                            reduced_motion=reduced_motion,
                        )
                    break
                if "content" in event:
                    text = event["content"]
                    output_chars += len(text)
                    if effective_output_format == "stream-json":
                        print(json.dumps({"type": "content", "text": text}))
                    elif effective_output_format == "text" and not fullscreen_mode:
                        _RICH.print_streaming_token(text, is_first=first_content_chunk)
                        if first_content_chunk:
                            _status_clear()
                            content_started = True
                            first_content_chunk = False
                    chunks.append(text)
                    continue
            
            # Check if we should re-run the stream due to plan approval
            if payload is None:
                break # Rejected
            if event.get("done"):
                break # Normal completion
            # If we reached here, it means we hit a 'break' inside 'if approved', so we re-run with new payload
            pass

        response_text = "".join(chunks)
        _status_clear()
        
        if effective_output_format == "text" and not fullscreen_mode:
            _RICH.finish_streaming()
        
        turn_duration = time.time() - turn_start
        
        if fullscreen_mode:
            _append_bounded(conversation_log, f"you: {_preview_line(user_input)}", 12)
            _append_bounded(conversation_log, f"atri: {_preview_line(response_text or '(no response)')}", 12)
            if tool_names:
                names = ", ".join(tool_names[:3])
                suffix = " ..." if len(tool_names) > 3 else ""
                _append_bounded(tool_log, f"turn {turn_number}: {names}{suffix}", 10)
            
            current_status = TurnStatus(
                turn_number=turn_number,
                elapsed_seconds=turn_duration,
                input_tokens=exact_input_tokens if has_exact_usage else input_tokens,
                output_tokens=exact_output_tokens if has_exact_usage else _estimate_tokens(response_text),
                tool_calls=tool_calls,
                phase="complete",
            )
            _render_interactive_dashboard(
                conversation_id=active_conversation_id,
                permission_state=permission_state,
                status=current_status,
                conversation_log=conversation_log,
                tool_log=tool_log,
                note=f"turn {turn_number} complete",
                reduced_motion=reduced_motion,
            )
        elif effective_output_format == "text":
            _print_turn_status_summary(
                turn_number,
                turn_start,
                exact_input_tokens if has_exact_usage else input_tokens,
                len(response_text),
                tool_calls,
                "complete",
                output_tokens_exact=exact_output_tokens if has_exact_usage else None,
            )
            if active_conversation_id:
                _print_info(f"conversation_id: {active_conversation_id}")


        if telemetry:
            if has_exact_usage:
                telemetry.total_input_tokens += exact_input_tokens
                telemetry.total_output_tokens += exact_output_tokens
            else:
                telemetry.total_input_tokens += input_tokens
                telemetry.total_output_tokens += _estimate_tokens(response_text)
            telemetry.add_turn(
                turn_number=turn_number,
                user_message=user_input,
                assistant_response=response_text,
                tool_calls=tool_names,
                duration_seconds=turn_duration,
            )
            exceeded, reason = telemetry.check_budget_limits()
            if exceeded:
                if effective_output_format in {"stream-json", "json"}:
                    print(json.dumps({"type": "error", "message": reason}))
                else:
                    _print_error(reason)
                return

        if effective_output_format == "json":
            result = {
                "type": "turn_result",
                "turn": turn_number,
                "response": response_text,
            }
            if active_conversation_id:
                result["conversation_id"] = active_conversation_id
            if telemetry:
                result["telemetry"] = telemetry.to_dict()
            print(json.dumps(result))
        elif effective_output_format == "stream-json":
            if active_conversation_id:
                print(json.dumps({"type": "conversation_id", "conversation_id": active_conversation_id}))
        else:
            if fullscreen_mode:
                current_status = TurnStatus(
                    turn_number=turn_number,
                    elapsed_seconds=turn_duration,
                    input_tokens=exact_input_tokens if has_exact_usage else input_tokens,
                    output_tokens=exact_output_tokens if has_exact_usage else _estimate_tokens(response_text),
                    tool_calls=tool_calls,
                    phase="complete",
                )
                _render_interactive_dashboard(
                    conversation_id=active_conversation_id,
                    permission_state=permission_state,
                    status=current_status,
                    conversation_log=conversation_log,
                    tool_log=tool_log,
                    note=f"turn {turn_number} complete",
                    reduced_motion=reduced_motion,
                )
            else:
                print()
                if not fullscreen_mode:
                    _RICH.finish_streaming()
                _print_turn_status_summary(
                    turn_number,
                    turn_start,
                    exact_input_tokens if has_exact_usage else input_tokens,
                    output_chars,
                    tool_calls,
                    "complete",
                    output_tokens_exact=exact_output_tokens if has_exact_usage else None,
                )
                if active_conversation_id:
                    _print_info(f"conversation_id: {active_conversation_id}")


def _sessions_list(client: OrchestratorClient) -> None:
    response = client.request_json("GET", "/conversations")
    conversations = response.get("conversations", [])
    if not conversations:
        _print_warning("No conversations found.")
        return

    print(_style("Conversations", color="cyan", bold=True))
    for item in conversations:
        print(
            f"{item['conversation_id']}\t{item['prompt_profile']}\t{item['updated_at']}"
        )


def _sessions_show(client: OrchestratorClient, conversation_id: str) -> None:
    response = client.request_json("GET", f"/conversations/{conversation_id}")
    convo = response.get("conversation", {})
    turns = response.get("turns", [])

    print(f"Conversation: {convo.get('conversation_id')}")
    print(f"Profile: {convo.get('prompt_profile')}")
    print(f"Turns: {len(turns)}")
    for turn in turns:
        print(f"\n[Turn {turn['turn_index']}] user: {turn['user_message']}")
        print(f"assistant: {turn['assistant_response']}")


def _sessions_resume(client: OrchestratorClient, conversation_id: str) -> None:
    response = client.request_json("POST", f"/conversations/{conversation_id}/resume")
    print(
        f"Conversation {response['conversation_id']} is resumable with {response['turn_count']} turns."
    )


def _sessions_fork(client: OrchestratorClient, conversation_id: str, new_id: Optional[str]) -> None:
    payload = {"new_conversation_id": new_id} if new_id else {}
    response = client.request_json("POST", f"/conversations/{conversation_id}/fork", payload)
    print(
        f"Fork created: {response['source_conversation_id']} -> {response['new_conversation_id']}"
    )


def _permissions_check(
    client: OrchestratorClient,
    tool_call: str,
    mode: str,
    allow: list[str],
    ask: list[str],
    deny: list[str],
) -> None:
    payload = {
        "tool_call": tool_call,
        "mode": mode,
        "allow": allow,
        "ask": ask,
        "deny": deny,
    }
    response = client.request_json("POST", "/permissions/evaluate", payload)
    print(f"decision={response['action']}")
    print(f"reason={response['reason']}")


def _mcp_list_tools(client: OrchestratorClient) -> None:
    response = client.request_json("GET", "/tools")
    tools = response.get("tools", [])
    if not tools:
        _print_warning("No tools available.")
        return

    print(_style(f"Available tools ({response.get('total', len(tools))})", color="cyan", bold=True) + "\n")
    for tool in tools:
        print(f"  {tool['name']}")
        if tool.get("description"):
            print(f"    {tool['description']}")
        print(f"    Server: {tool['server']}")
        if tool.get("category"):
            print(f"    Category: {tool['category']}")
        print()


def _mcp_status(client: OrchestratorClient) -> None:
    response = client.request_json("GET", "/health")
    print(_style(f"Status: {response.get('status')}", color="cyan", bold=True))
    print(f"Ready: {response.get('ready')}")
    print(f"LLM connected: {response.get('llm_connected')}")
    readiness_issues = response.get("readiness_issues") or []
    if readiness_issues:
        print("Readiness issues:")
        for issue in readiness_issues:
            print(f"  - {issue}")

    mcp_servers = response.get("mcp_servers", {})
    if mcp_servers:
        print("\n" + _style("MCP servers:", color="cyan", bold=True))
        for server_name, server_status in mcp_servers.items():
            print(f"  {server_name}: {server_status.get('status', 'unknown')}")
    else:
        print("\nNo MCP servers configured.")

    startup_summary = response.get("startup_summary") or {}
    if startup_summary:
        failed = startup_summary.get("failed_servers") or []
        initialized = startup_summary.get("initialized_servers") or []
        print("\n" + _style("Startup summary:", color="cyan", bold=True))
        print(f"  initialized_servers={len(initialized)}")
        print(f"  failed_servers={len(failed)}")
        recommendations = startup_summary.get("recommendations") or []
        if recommendations:
            print("  recommendations:")
            for recommendation in recommendations:
                print(f"    - {recommendation}")


def _mcp_startup_summary(client: OrchestratorClient) -> None:
    response = client.request_json("GET", "/mcp/startup-summary")
    summary = response.get("summary") or {}
    print(_style("MCP startup summary", color="cyan", bold=True))
    print(f"Initialized servers: {', '.join(summary.get('initialized_servers') or []) or 'none'}")
    print(f"Failed servers: {', '.join(summary.get('failed_servers') or []) or 'none'}")
    recommendations = summary.get("recommendations") or []
    if recommendations:
        print("Recommendations:")
        for recommendation in recommendations:
            print(f"  - {recommendation}")


def _mcp_refresh(client: OrchestratorClient, use_cache: bool, clear_cache: bool) -> None:
    force_refresh = not use_cache
    response = client.request_json(
        "POST",
        f"/tools/refresh?force_refresh={'true' if force_refresh else 'false'}&clear_cache={'true' if clear_cache else 'false'}",
    )
    print(f"Refresh status: {response.get('status')}")
    if response.get("error_code"):
        print(f"Error code: {response.get('error_code')}")
    print(f"Total tools discovered: {response.get('total_discovered')}")
    servers = response.get("servers", {})
    metadata = response.get("refresh_metadata", {})
    if servers:
        print("\nTools by server:")
        for server_name, count in servers.items():
            server_meta = metadata.get(server_name) or {}
            source = server_meta.get("source", "unknown")
            line = f"  {server_name}: {count} tools (source={source})"
            if server_meta.get("error_code"):
                line += f" error_code={server_meta.get('error_code')}"
            print(line)
            if server_meta.get("recommended_fix"):
                print(f"    fix: {server_meta.get('recommended_fix')}")


def _mcp_reconnect(client: OrchestratorClient, server_name: str) -> None:
    response = client.request_json("POST", "/mcp/reconnect", {"server": server_name})
    print(f"Reconnection status: {response.get('status')}")
    if response.get("error_code"):
        print(f"Error code: {response.get('error_code')}")
    print(f"Attempts used: {response.get('attempts_used')}")
    print(f"Attempts remaining: {response.get('attempts_remaining')}")
    if response.get("next_retry_after_seconds") is not None:
        print(f"Next retry after: {response.get('next_retry_after_seconds')}s")
    if response.get("success"):
        print(f"Successfully reconnected to {server_name}")
    else:
        print(f"Failed to reconnect to {server_name}")
        print(f"Reason: {response.get('reason')}")
        if response.get("recommended_fix"):
            print(f"Recommended fix: {response.get('recommended_fix')}")


def _mcp_deferred(client: OrchestratorClient, server_name: str, enabled: bool) -> None:
    response = client.request_json(
        "POST",
        "/mcp/deferred-discovery",
        {"server": server_name, "enabled": enabled}
    )
    print(f"Deferred discovery status: {response.get('status')}")
    print(f"Server: {server_name}")
    print(f"Enabled: {response.get('enabled')}")


def _worktrees_list() -> None:
    """List available worktrees."""
    try:
        from orchestrator.worktree_manager import WorktreeManager
        manager = WorktreeManager()
        worktrees = manager.list_worktrees()
        if not worktrees:
            print("No worktrees found.")
            return
        
        print(f"Active worktrees ({len(worktrees)}):\n")
        for wt in worktrees:
            status = "dirty" if wt.is_dirty else "clean"
            print(f"  {wt.path}")
            print(f"    Conversation: {wt.conversation_id}")
            print(f"    Branch: {wt.branch}")
            print(f"    Status: {status}")
            print()
    except Exception as e:
        print(f"Error listing worktrees: {e}")


def _worktrees_clean() -> None:
    """Clean up dirty worktrees."""
    try:
        from orchestrator.worktree_manager import WorktreeManager
        manager = WorktreeManager()
        dirty = manager.cleanup_dirty_worktrees(auto_clean=False)
        if not dirty:
            print("No dirty worktrees found.")
            return
        
        print(f"Dirty worktrees ({len(dirty)}):")
        for name, needs_cleanup in dirty.items():
            if needs_cleanup:
                print(f"  {name}: cleaned")
            else:
                print(f"  {name}: requires manual cleanup")
    except Exception as e:
        print(f"Error cleaning worktrees: {e}")


def _cleanup(mode: str, assume_yes: bool) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "scripts" / "reset_local_state.py"
    if not script.exists():
        raise RuntimeError(f"cleanup script not found: {script}")

    command = [sys.executable, str(script)]
    if assume_yes:
        command.append("--yes")
    if mode in {"deep", "docker"}:
        command.append("--include-frontend-build")
    if mode == "docker":
        command.append("--with-docker-volumes")

    completed = subprocess.run(
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout.rstrip())
    if completed.returncode != 0:
        if completed.stderr:
            print(completed.stderr.rstrip(), file=sys.stderr)
        raise RuntimeError(f"cleanup failed (mode={mode}, exit={completed.returncode})")


def _stop_services():
    """Explicitly stop background services."""
    manager = ServiceManager()
    status = manager.status()
    
    _RICH.render_info("Stopping Atri Code services...")
    
    # We need to manually terminate existing processes by port since we might not 'own' them in this instance
    def kill_port(port):
        import signal
        try:
            # Use fuser or lsof to find PIDs
            res = subprocess.run(["lsof", "-t", f"-i:{port}"], capture_output=True, text=True)
            for pid in res.stdout.strip().split():
                if pid:
                    os.kill(int(pid), signal.SIGTERM)
        except Exception:
            pass

    kill_port(manager.llama_port)
    kill_port(manager.orch_port)
    
    _RICH.render_success("Services stopped")


def _upgrade():
    """
    Downloads and executes the latest Atri Code installer from GitHub.
    This provides a seamless way to receive performance updates and model adapters.
    """
    import urllib.request
    import subprocess
    
    _RICH.render_info("Checking for updates...")
    installer_url = "https://raw.githubusercontent.com/ToniBirat7/Agentic_AI/master/install.sh"
    
    try:
        req = urllib.request.Request(installer_url, headers={"User-Agent": "atri-cli/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            script_content = resp.read().decode("utf-8")
            
        _RICH.render_info("Update found! Running installer...")
        # Run the script via bash
        proc = subprocess.Popen(["bash"], stdin=subprocess.PIPE, text=True)
        proc.communicate(input=script_content)
        
        if proc.returncode == 0:
            _RICH.render_success("Atri Code upgraded successfully")
        else:
            _RICH.render_error(f"Upgrade failed with exit code {proc.returncode}")
            
    except Exception as e:
        _RICH.render_error(f"Upgrade failed: {e}")


def _doctor(client: OrchestratorClient, output_format: str) -> None:
    checks: list[dict[str, Any]] = []

    def _record(name: str, path: str) -> None:
        try:
            response = client.request_json("GET", path)
            checks.append({"name": name, "ok": True, "path": path, "response": response})
        except Exception as exc:
            checks.append({"name": name, "ok": False, "path": path, "error": str(exc)})

    _record("liveness", "/live")
    _record("health", "/health")
    _record("readiness", "/ready")
    _record("tools", "/tools")

    all_ok = all(item["ok"] for item in checks)
    if output_format in {"json", "stream-json"}:
        print(json.dumps({"type": "doctor", "ok": all_ok, "checks": checks}))
    elif RichTUI.is_available():
        _RICH.render_doctor(checks)
    else:
        print(_style("Atri Code doctor", color="cyan", bold=True))
        for item in checks:
            status = "ok" if item["ok"] else "failed"
            prefix = _style("[ok]", color="green", bold=True) if item["ok"] else _style("[failed]", color="red", bold=True)
            print(f"{prefix} {item['name']} {item['path']} -> {status}")
            if not item["ok"]:
                print(f"  error={item['error']}")

        if all_ok:
            _print_success("Doctor checks passed. Runtime is ready.")
        else:
            _print_error("Doctor checks failed. Run `atri-cli mcp status` and inspect orchestrator logs.")
            raise SystemExit(1)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Atri Code CLI")
    parser.add_argument("--prompt", help="Prompt for print/interactive mode")
    parser.add_argument("-p", "--print", action="store_true", dest="print_mode", help="Run one-shot mode and exit")
    parser.add_argument("-r", "--resume", help="Resume a conversation id")
    parser.add_argument("--api-url", default=_env_first("ATRI_API_URL", "TARBAR_API_URL", default="http://127.0.0.1:8001"))
    parser.add_argument("--api-key", default=_env_first("ATRI_API_KEY", "TARBAR_API_KEY"))
    parser.add_argument(
        "--allowed-directory",
        default=_env_first("ATRI_ALLOWED_DIRECTORY", "TARBAR_ALLOWED_DIRECTORY"),
        help="Optional filesystem scope root",
    )
    parser.add_argument(
        "--permission-mode",
        default=_env_first("ATRI_PERMISSION_MODE", "TARBAR_PERMISSION_MODE", default="default"),
        choices=sorted(PERMISSION_MODES),
        help="Runtime permission mode for tool-call checks",
    )
    parser.add_argument(
        "--allow-rule",
        action="append",
        default=[],
        help="Initial allow rule (repeatable)",
    )
    parser.add_argument(
        "--ask-rule",
        action="append",
        default=[],
        help="Initial ask rule (repeatable)",
    )
    parser.add_argument(
        "--deny-rule",
        action="append",
        default=[],
        help="Initial deny rule (repeatable)",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=None,
        help="Maximum number of turns allowed in this session",
    )
    parser.add_argument(
        "--max-budget-usd",
        type=float,
        default=None,
        help="Maximum budget in USD for this session",
    )
    parser.add_argument(
        "--output-format",
        choices=("text", "json", "stream-json"),
        default=None,
        help="Output format for session results",
    )
    parser.add_argument(
        "--stream-json",
        action="store_true",
        help="Output streaming results as JSON for CI pipelines",
    )
    parser.add_argument(
        "--timeline-verbosity",
        choices=TIMELINE_VERBOSITY_LEVELS,
        default=_env_first("ATRI_TIMELINE_VERBOSITY", "TARBAR_TIMELINE_VERBOSITY", default="normal"),
        help="Timeline verbosity for text mode: minimal, normal, debug",
    )
    parser.add_argument(
        "--telemetry",
        action="store_true",
        help="Print telemetry summary after session completes",
    )

    subparsers = parser.add_subparsers(dest="command")

    sessions = subparsers.add_parser("sessions", help="Session management")
    sessions_sub = sessions.add_subparsers(dest="sessions_command", required=True)

    sessions_sub.add_parser("list", help="List conversations")

    show = sessions_sub.add_parser("show", help="Show conversation transcript")
    show.add_argument("conversation_id")

    resume = sessions_sub.add_parser("resume", help="Validate conversation can resume")
    resume.add_argument("conversation_id")

    fork = sessions_sub.add_parser("fork", help="Fork conversation")
    fork.add_argument("conversation_id")
    fork.add_argument("--new-id", help="Optional explicit id for the forked conversation")

    permissions = subparsers.add_parser("permissions", help="Permission helpers")
    permissions_sub = permissions.add_subparsers(dest="permissions_command", required=True)
    check = permissions_sub.add_parser("check", help="Evaluate a tool call against mode/rules")
    check.add_argument("--tool-call", required=True, help="Tool call string, e.g. Bash(git status)")
    check.add_argument("--mode", default="default", help="Permission mode")
    check.add_argument("--allow", action="append", default=[], help="Allow rule (repeatable)")
    check.add_argument("--ask", action="append", default=[], help="Ask rule (repeatable)")
    check.add_argument("--deny", action="append", default=[], help="Deny rule (repeatable)")

    mcp = subparsers.add_parser("mcp", help="MCP server and tool inspection")
    mcp_sub = mcp.add_subparsers(dest="mcp_command", required=True)
    mcp_sub.add_parser("tools", help="List available MCP tools")
    mcp_sub.add_parser("status", help="Show MCP server health and status")
    mcp_sub.add_parser("startup-summary", help="Show MCP startup trace summary")
    refresh = mcp_sub.add_parser("refresh", help="Refresh tool discovery from all MCP servers")
    
    subparsers.add_parser("stop", help="Stop all background services (llama-server, orchestrator)")
    subparsers.add_parser("upgrade", help="Upgrade Atri Code to the latest version")
    subparsers.add_parser("doctor", help="Run health diagnostics and auto-start services")
    refresh.add_argument(
        "--cached",
        action="store_true",
        help="Allow cached discovery results instead of forcing fresh discovery",
    )
    refresh.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear discovery cache before refreshing",
    )
    
    reconnect = mcp_sub.add_parser("reconnect", help="Reconnect to a failed MCP server")
    reconnect.add_argument("server", help="Server name to reconnect to")
    
    deferred = mcp_sub.add_parser("deferred", help="Manage deferred tool discovery")
    deferred.add_argument("server", help="Server name")
    deferred.add_argument("--enable", action="store_true", help="Enable deferred discovery")
    deferred.add_argument("--disable", action="store_true", help="Disable deferred discovery")

    worktrees = subparsers.add_parser("worktrees", help="Manage git worktrees for parallel work")
    worktrees_sub = worktrees.add_subparsers(dest="worktrees_command", required=True)
    worktrees_sub.add_parser("list", help="List active worktrees")
    worktrees_sub.add_parser("clean", help="Clean up dirty worktrees")

    cleanup = subparsers.add_parser("cleanup", help="Clean runtime caches and local artifacts")
    cleanup.add_argument(
        "--mode",
        choices=("safe", "deep", "docker"),
        default="safe",
        help="safe: caches/db only, deep: include frontend build cache, docker: also reset docker volumes",
    )
    cleanup.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )



    return parser


def main() -> None:
    parser = _build_parser()
    argv = sys.argv[1:]
    known_commands = {"sessions", "permissions", "mcp", "worktrees", "doctor", "cleanup", "stop", "upgrade"}
    if argv and not argv[0].startswith("-") and argv[0] not in known_commands:
        # Convenience mode: `atri-cli "prompt"` maps to print mode.
        prompt = " ".join(argv)
        args = parser.parse_args(["--print", "--prompt", prompt])
    else:
        args = parser.parse_args()

    # ── Auto-start services ────────────────────────────────────────────
    svc = ServiceManager()

    # Doctor command can run even without services
    if args.command not in {"cleanup", "stop"}:
        if not svc.ensure_services(tui=_RICH):
            raise SystemExit(1)

    # Resolve allowed_directory to absolute path if provided
    if args.allowed_directory:
        args.allowed_directory = os.path.abspath(os.path.expanduser(args.allowed_directory))

    client = OrchestratorClient(base_url=args.api_url, api_key=args.api_key)
    permission_state = PermissionState(
        mode=args.permission_mode,
        allow=list(args.allow_rule),
        ask=list(args.ask_rule),
        deny=list(args.deny_rule),
    )

    # Initialize telemetry for chat sessions
    telemetry = SessionTelemetry(
        mode="print" if args.print_mode or args.prompt else "interactive",
        permission_mode=args.permission_mode,
        max_turns=args.max_turns,
        max_budget_usd=args.max_budget_usd,
    )
    output_format = args.output_format or ("stream-json" if args.stream_json else "text")
    _TUI.set_timeline_verbosity(args.timeline_verbosity)

    def _graceful_exit(signum=None, frame=None):
        """Handle Ctrl+C cleanly."""
        print()  # newline after ^C
        _RICH.render_info("Shutting down...")
        svc.shutdown()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _graceful_exit)
    signal.signal(signal.SIGTERM, _graceful_exit)

    try:
        if args.command == "sessions":
            if args.sessions_command == "list":
                _sessions_list(client)
                return
            if args.sessions_command == "show":
                _sessions_show(client, args.conversation_id)
                return
            if args.sessions_command == "resume":
                _sessions_resume(client, args.conversation_id)
                return
            if args.sessions_command == "fork":
                _sessions_fork(client, args.conversation_id, args.new_id)
                return

        if args.command == "permissions":
            if args.permissions_command == "check":
                _permissions_check(
                    client,
                    tool_call=args.tool_call,
                    mode=args.mode,
                    allow=args.allow,
                    ask=args.ask,
                    deny=args.deny,
                )
                return

        if args.command == "mcp":
            if args.mcp_command == "tools":
                _mcp_list_tools(client)
                return
            if args.mcp_command == "status":
                _mcp_status(client)
                return
            if args.mcp_command == "startup-summary":
                _mcp_startup_summary(client)
                return
            if args.mcp_command == "refresh":
                _mcp_refresh(client, use_cache=args.cached, clear_cache=args.clear_cache)
                return
            if args.mcp_command == "reconnect":
                _mcp_reconnect(client, args.server)
                return
            if args.mcp_command == "deferred":
                if not args.enable and not args.disable:
                    _emit_error(output_format, "specify --enable or --disable")
                    raise SystemExit(1)
                _mcp_deferred(client, args.server, args.enable)
                return

        if args.command == "worktrees":
            if args.worktrees_command == "list":
                _worktrees_list()
                return
            if args.worktrees_command == "clean":
                _worktrees_clean()
                return

        if args.command == "stop":
            _stop_services()
            return

        if args.command == "upgrade":
            _upgrade()
            return

        if args.command == "doctor":
            _doctor(client, output_format=output_format)
            return

        if args.command == "cleanup":
            _cleanup(args.mode, args.yes)
            return

        if args.print_mode:
            if not args.prompt:
                _emit_error(output_format, "Print mode requires a prompt")
                raise SystemExit(1)
            _run_print_mode(
                client,
                prompt=args.prompt,
                conversation_id=args.resume,
                allowed_directory=args.allowed_directory,
                permission_state=permission_state,
                telemetry=telemetry,
                output_format=output_format,
                stream_json=args.stream_json,
            )
            if args.telemetry:
                if output_format != "json":
                    print("\n" + telemetry.summary())
            return

        if args.prompt:
            _run_print_mode(
                client,
                prompt=args.prompt,
                conversation_id=args.resume,
                allowed_directory=args.allowed_directory,
                permission_state=permission_state,
                telemetry=telemetry,
                output_format=output_format,
                stream_json=args.stream_json,
            )
            if args.telemetry:
                if output_format != "json":
                    print("\n" + telemetry.summary())
            return

        _run_interactive(
            client,
            conversation_id=args.resume,
            allowed_directory=args.allowed_directory,
            permission_state=permission_state,
            telemetry=telemetry,
            output_format=output_format,
            stream_json=args.stream_json,
        )
        if args.telemetry:
            if output_format != "json":
                print("\n" + telemetry.summary())
    except KeyboardInterrupt:
        _graceful_exit()
    except RuntimeError as exc:
        _emit_error(output_format, str(exc))
        raise SystemExit(1)
    finally:
        svc.shutdown()


if __name__ == "__main__":
    main()
