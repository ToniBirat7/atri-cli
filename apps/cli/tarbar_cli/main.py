from __future__ import annotations

import argparse
import os
import sys
import json
import time
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .client import OrchestratorClient
from .telemetry import SessionTelemetry
from .tui import TUIRenderer, TIMELINE_VERBOSITY_LEVELS, TurnStatus


PERMISSION_MODES = {
    "default",
    "plan",
    "dontAsk",
    "bypassPermissions",
    "acceptEdits",
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
    return (
        "Commands:\n"
        "  /help               Show this help\n"
        "  /mode               Show current permission mode\n"
        "  /mode <name>        Set permission mode\n"
        "  /timeline           Show timeline verbosity\n"
        "  /timeline <level>   Set timeline verbosity (minimal/normal/debug)\n"
        "  /exit | /quit       Exit interactive mode"
    )


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


def _render_timeline_event(event: dict[str, Any], output_format: str) -> None:
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
        print(_interactive_help_text())
        return True

    if user_input == "/mode":
        print(
            f"permission_mode={permission_state.mode} "
            f"allow={len(permission_state.allow)} ask={len(permission_state.ask)} deny={len(permission_state.deny)}"
        )
        return True

    if user_input.startswith("/mode "):
        requested = user_input.split(None, 1)[1].strip()
        if requested not in PERMISSION_MODES:
            valid = ", ".join(sorted(PERMISSION_MODES))
            print(f"Unknown mode: {requested}. Valid modes: {valid}")
            return True
        permission_state.mode = requested
        print(f"permission_mode set to {requested}")
        return True

    if user_input == "/timeline":
        print(f"timeline_verbosity={_TUI.timeline_verbosity}")
        return True

    if user_input.startswith("/timeline "):
        requested = user_input.split(None, 1)[1].strip()
        if requested not in TIMELINE_VERBOSITY_LEVELS:
            valid = ", ".join(TIMELINE_VERBOSITY_LEVELS)
            print(f"Unknown timeline verbosity: {requested}. Valid levels: {valid}")
            return True
        _TUI.set_timeline_verbosity(requested)
        print(f"timeline_verbosity set to {requested}")
        return True

    return False


def _render_permission_event(
    client: OrchestratorClient,
    event: dict[str, Any],
    permission_state: PermissionState,
    allowed_directory: Optional[str],
    interactive: bool,
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

        print(f"[safety] Write target outside allowed directory: {target_path}")
        if interactive:
            allowed = _prompt_write_target(tool_name, target_path)
            if allowed:
                permission_state.allow.append(f"{tool_name}({target_path})")
                print(f"[permission] Added allow rule for {tool_name}({target_path})")
            else:
                permission_state.deny.append(f"{tool_name}({target_path})")
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
            raise RuntimeError(event["error"])
        if "content" in event:
            text = event["content"]
            output_chars += len(text)
            if effective_output_format == "stream-json":
                print(json.dumps({"type": "content", "text": text}))
            elif effective_output_format == "text":
                if first_content_chunk:
                    _status_clear()
                    print(_style("assistant> ", color="cyan", bold=True), end="", flush=True)
                    first_content_chunk = False
                    content_started = True
                print(text, end="", flush=True)
            chunks.append(text)
            continue

    response_text = "".join(chunks)
    _status_clear()
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


def _run_interactive(
    client: OrchestratorClient,
    conversation_id: Optional[str],
    allowed_directory: Optional[str],
    permission_state: PermissionState,
    telemetry: Optional[SessionTelemetry] = None,
    output_format: str = "text",
    stream_json: bool = False,
) -> None:
    _TUI.print_welcome_dashboard(permission_state.mode, client.base_url)
    print(_style("Type /help for commands.", dim=True))
    print(_style("Use /mode or /mode <name> to inspect/change permission mode for this session.", dim=True))
    if conversation_id:
        _print_info(f"Resuming conversation: {conversation_id}")

    active_conversation_id = conversation_id
    turn_number = 0
    effective_output_format = "stream-json" if stream_json else output_format

    while True:
        try:
            user_input = input(f"\n{_style(f'tarbar[{permission_state.mode}]> ', color='cyan', bold=True)}").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            return

        if not user_input:
            continue
        if user_input in {"/exit", "/quit"}:
            _print_success("Goodbye.")
            return
        if _handle_interactive_local_command(user_input, permission_state):
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
        if effective_output_format == "text":
            _print_turn_card(turn_number, permission_state.mode)
            _update_live_status(turn_number, turn_start, input_tokens, output_chars, tool_calls, "thinking")

        chunks: list[str] = []
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
                    interactive=True,
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
                break
            if "content" in event:
                text = event["content"]
                output_chars += len(text)
                if effective_output_format == "stream-json":
                    print(json.dumps({"type": "content", "text": text}))
                elif effective_output_format == "text":
                    if not chunks:
                        _status_clear()
                        print(_style("assistant> ", color="cyan", bold=True), end="", flush=True)
                        content_started = True
                    print(text, end="", flush=True)
                else:
                    pass
                chunks.append(text)

        response_text = "".join(chunks)
        _status_clear()
        turn_duration = time.time() - turn_start

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
    print(f"LLM connected: {response.get('llm_connected')}")
    mcp_servers = response.get("mcp_servers", {})
    if mcp_servers:
        print("\n" + _style("MCP servers:", color="cyan", bold=True))
        for server_name, server_status in mcp_servers.items():
            print(f"  {server_name}: {server_status.get('status', 'unknown')}")
    else:
        print("\nNo MCP servers configured.")


def _mcp_refresh(client: OrchestratorClient) -> None:
    response = client.request_json("POST", "/tools/refresh")
    print(f"Refresh status: {response.get('status')}")
    print(f"Total tools discovered: {response.get('total_discovered')}")
    servers = response.get("servers", {})
    if servers:
        print("\nTools by server:")
        for server_name, count in servers.items():
            print(f"  {server_name}: {count} tools")


def _mcp_reconnect(client: OrchestratorClient, server_name: str) -> None:
    response = client.request_json("POST", "/mcp/reconnect", {"server": server_name})
    print(f"Reconnection status: {response.get('status')}")
    if response.get("success"):
        print(f"Successfully reconnected to {server_name}")
    else:
        print(f"Failed to reconnect to {server_name}")
        print(f"Reason: {response.get('reason')}")


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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tarbar CLI")
    parser.add_argument("--prompt", help="Prompt for print/interactive mode")
    parser.add_argument("-p", "--print", action="store_true", dest="print_mode", help="Run one-shot mode and exit")
    parser.add_argument("-r", "--resume", help="Resume a conversation id")
    parser.add_argument("--api-url", default=os.getenv("TARBAR_API_URL", "http://127.0.0.1:8001"))
    parser.add_argument("--api-key", default=os.getenv("TARBAR_API_KEY"))
    parser.add_argument(
        "--allowed-directory",
        default=os.getenv("TARBAR_ALLOWED_DIRECTORY"),
        help="Optional filesystem scope root",
    )
    parser.add_argument(
        "--permission-mode",
        default=os.getenv("TARBAR_PERMISSION_MODE", "default"),
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
        default=os.getenv("TARBAR_TIMELINE_VERBOSITY", "normal"),
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
    mcp_sub.add_parser("refresh", help="Refresh tool discovery from all MCP servers")
    
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

    return parser


def main() -> None:
    parser = _build_parser()
    argv = sys.argv[1:]
    known_commands = {"sessions", "permissions", "mcp", "worktrees"}
    if argv and not argv[0].startswith("-") and argv[0] not in known_commands:
        # Convenience mode: `tarbar "prompt"` maps to print mode.
        prompt = " ".join(argv)
        args = parser.parse_args(["--print", "--prompt", prompt])
    else:
        args = parser.parse_args()

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
            if args.mcp_command == "refresh":
                _mcp_refresh(client)
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
    except RuntimeError as exc:
        _emit_error(output_format, str(exc))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
