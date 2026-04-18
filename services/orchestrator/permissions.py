"""Permission evaluation primitives for tool calls.

This is an incremental rules engine for CLI and API usage.
Rules precedence is deny > ask > allow.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Iterable


READ_ONLY_TOOLS = {
    "Read",
    "Glob",
    "Grep",
    "LS",
    "list_directory",
    "read_file",
    "search_files",
}


@dataclass(slots=True)
class PermissionDecision:
    action: str  # allow | ask | deny
    reason: str


def _normalize_rule(rule: str) -> str:
    return (rule or "").strip()


def _rule_matches(rule: str, tool_call: str) -> bool:
    normalized_rule = _normalize_rule(rule)
    if not normalized_rule:
        return False

    # Exact match first.
    if normalized_rule == tool_call:
        return True

    # Tool-only match, e.g. Bash matches Bash(git status)
    if "(" not in normalized_rule:
        return tool_call == normalized_rule or tool_call.startswith(normalized_rule + "(")

    # Glob wildcard matching for specifier expressions.
    return fnmatch.fnmatch(tool_call, normalized_rule)


def _first_matching_rule(rules: Iterable[str], tool_call: str) -> str | None:
    for rule in rules:
        if _rule_matches(rule, tool_call):
            return rule
    return None


def evaluate_permission(
    *,
    tool_call: str,
    mode: str,
    allow_rules: list[str],
    ask_rules: list[str],
    deny_rules: list[str],
) -> PermissionDecision:
    """Evaluate a permission decision for one tool invocation string."""
    tool_call = (tool_call or "").strip()
    if not tool_call:
        return PermissionDecision(action="deny", reason="Tool call is empty")

    denied = _first_matching_rule(deny_rules, tool_call)
    if denied:
        return PermissionDecision(action="deny", reason=f"Matched deny rule: {denied}")

    mode = (mode or "default").strip()

    if mode == "dontAsk":
        allowed = _first_matching_rule(allow_rules, tool_call)
        if allowed:
            return PermissionDecision(action="allow", reason=f"Matched allow rule: {allowed}")
        return PermissionDecision(action="deny", reason="Mode dontAsk denies tool calls without explicit allow")

    if mode == "plan":
        tool_name = tool_call.split("(", 1)[0]
        if tool_name in READ_ONLY_TOOLS:
            return PermissionDecision(action="allow", reason="Plan mode allows read-only tools")
        return PermissionDecision(action="deny", reason="Plan mode blocks state-changing tools")

    asked = _first_matching_rule(ask_rules, tool_call)
    if asked:
        return PermissionDecision(action="ask", reason=f"Matched ask rule: {asked}")

    allowed = _first_matching_rule(allow_rules, tool_call)
    if allowed:
        return PermissionDecision(action="allow", reason=f"Matched allow rule: {allowed}")

    if mode in {"bypassPermissions", "acceptEdits"}:
        return PermissionDecision(action="allow", reason=f"Mode {mode} allows tool call by default")

    return PermissionDecision(action="ask", reason="No matching rule; defaulting to ask")
