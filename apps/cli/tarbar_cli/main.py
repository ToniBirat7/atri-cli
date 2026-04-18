from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .client import OrchestratorClient


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


@dataclass
class PermissionState:
    mode: str = "default"
    allow: list[str] = field(default_factory=list)
    ask: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)
    prompted_write_targets: set[str] = field(default_factory=set)


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
) -> str:
    chunks: list[str] = []
    active_conversation_id = payload.get("conversation_id")

    for event in client.stream_chat(payload):
        if event.get("done"):
            break
        if "event" in event and isinstance(event["event"], dict):
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
            continue
        if "error" in event:
            raise RuntimeError(event["error"])
        if "content" in event:
            text = event["content"]
            print(text, end="", flush=True)
            chunks.append(text)
            continue

    print()
    if active_conversation_id:
        print(f"\n[conversation_id] {active_conversation_id}")
    return "".join(chunks)


def _run_print_mode(
    client: OrchestratorClient,
    prompt: str,
    conversation_id: Optional[str],
    allowed_directory: Optional[str],
    permission_state: PermissionState,
) -> None:
    payload = _build_payload(prompt, conversation_id, allowed_directory)
    _print_stream_response(
        client,
        payload,
        permission_state=permission_state,
        allowed_directory=allowed_directory,
        interactive=False,
    )


def _run_interactive(
    client: OrchestratorClient,
    conversation_id: Optional[str],
    allowed_directory: Optional[str],
    permission_state: PermissionState,
) -> None:
    print("Tarbar CLI interactive mode. Type /exit to quit.")
    print("Use /mode or /mode <name> to inspect/change permission mode for this session.")
    if conversation_id:
        print(f"Resuming conversation: {conversation_id}")

    active_conversation_id = conversation_id

    while True:
        try:
            user_input = input("\ntarbar> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            return

        if not user_input:
            continue
        if user_input in {"/exit", "/quit"}:
            print("Goodbye.")
            return
        if _handle_interactive_local_command(user_input, permission_state):
            continue

        payload = _build_payload(user_input, active_conversation_id, allowed_directory)

        chunks: list[str] = []
        for event in client.stream_chat(payload):
            if event.get("done"):
                break
            if "event" in event and isinstance(event["event"], dict):
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
                continue
            if "error" in event:
                print(f"\n[error] {event['error']}")
                break
            if "content" in event:
                text = event["content"]
                print(text, end="", flush=True)
                chunks.append(text)

        if chunks:
            print()
        if active_conversation_id:
            print(f"[conversation_id] {active_conversation_id}")


def _sessions_list(client: OrchestratorClient) -> None:
    response = client.request_json("GET", "/conversations")
    conversations = response.get("conversations", [])
    if not conversations:
        print("No conversations found.")
        return

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
        print("No tools available.")
        return

    print(f"Available tools ({response.get('total', len(tools))}):\n")
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
    print(f"Status: {response.get('status')}")
    print(f"LLM connected: {response.get('llm_connected')}")
    mcp_servers = response.get("mcp_servers", {})
    if mcp_servers:
        print("\nMCP servers:")
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
                print("Error: specify --enable or --disable")
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
            raise SystemExit("Print mode requires a prompt")
        _run_print_mode(
            client,
            prompt=args.prompt,
            conversation_id=args.resume,
            allowed_directory=args.allowed_directory,
            permission_state=permission_state,
        )
        return

    if args.prompt:
        _run_print_mode(
            client,
            prompt=args.prompt,
            conversation_id=args.resume,
            allowed_directory=args.allowed_directory,
            permission_state=permission_state,
        )
        return

    _run_interactive(
        client,
        conversation_id=args.resume,
        allowed_directory=args.allowed_directory,
        permission_state=permission_state,
    )


if __name__ == "__main__":
    main()
