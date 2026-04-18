from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from .client import OrchestratorClient


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


def _print_stream_response(client: OrchestratorClient, payload: dict) -> str:
    chunks: list[str] = []
    active_conversation_id = payload.get("conversation_id")

    for event in client.stream_chat(payload):
        if event.get("done"):
            break
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
) -> None:
    payload = _build_payload(prompt, conversation_id, allowed_directory)
    _print_stream_response(client, payload)


def _run_interactive(
    client: OrchestratorClient,
    conversation_id: Optional[str],
    allowed_directory: Optional[str],
) -> None:
    print("Tarbar CLI interactive mode. Type /exit to quit.")
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

        payload = _build_payload(user_input, active_conversation_id, allowed_directory)

        chunks: list[str] = []
        for event in client.stream_chat(payload):
            if event.get("done"):
                break
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

    return parser


def main() -> None:
    parser = _build_parser()
    argv = sys.argv[1:]
    known_commands = {"sessions", "permissions"}
    if argv and not argv[0].startswith("-") and argv[0] not in known_commands:
        # Convenience mode: `tarbar "prompt"` maps to print mode.
        prompt = " ".join(argv)
        args = parser.parse_args(["--print", "--prompt", prompt])
    else:
        args = parser.parse_args()

    client = OrchestratorClient(base_url=args.api_url, api_key=args.api_key)

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

    if args.print_mode:
        if not args.prompt:
            raise SystemExit("Print mode requires a prompt")
        _run_print_mode(
            client,
            prompt=args.prompt,
            conversation_id=args.resume,
            allowed_directory=args.allowed_directory,
        )
        return

    if args.prompt:
        _run_print_mode(
            client,
            prompt=args.prompt,
            conversation_id=args.resume,
            allowed_directory=args.allowed_directory,
        )
        return

    _run_interactive(
        client,
        conversation_id=args.resume,
        allowed_directory=args.allowed_directory,
    )


if __name__ == "__main__":
    main()
