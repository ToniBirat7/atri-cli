"""Tests for permission rule evaluation."""

from permissions import evaluate_permission


def test_deny_wins_over_allow():
    decision = evaluate_permission(
        tool_call="Bash(git push origin main)",
        mode="default",
        allow_rules=["Bash(*)"],
        ask_rules=[],
        deny_rules=["Bash(git push*)"],
    )
    assert decision.action == "deny"


def test_plan_mode_allows_read_only_tools():
    decision = evaluate_permission(
        tool_call="read_file(path=/tmp/a)",
        mode="plan",
        allow_rules=[],
        ask_rules=[],
        deny_rules=[],
    )
    assert decision.action == "allow"


def test_dontask_requires_allow_rule():
    decision = evaluate_permission(
        tool_call="Edit(/tmp/a)",
        mode="dontAsk",
        allow_rules=[],
        ask_rules=[],
        deny_rules=[],
    )
    assert decision.action == "deny"


def test_default_mode_falls_back_to_ask():
    decision = evaluate_permission(
        tool_call="Bash(git status)",
        mode="default",
        allow_rules=[],
        ask_rules=[],
        deny_rules=[],
    )
    assert decision.action == "ask"
