"""Snapshot tests for prompt_policy profiles."""
import datetime
import re

import pytest

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from prompt_policy import build_system_prompt, normalize_prompt_profile, VALID_PROMPT_PROFILES


COMMON_KWARGS = dict(
    assistant_name="Atri",
    model_name="gemma-4-e2b-it-Q4_K_M",
    current_date="2026-01-01",
    fallback_text="No info.",
    disclaimer_text="Not legal advice.",
    legal_help_line="Call 1-800-HELP",
)


@pytest.mark.parametrize("profile", VALID_PROMPT_PROFILES)
def test_profile_builds_without_error(profile):
    prompt = build_system_prompt(profile, enable_thinking=False, **COMMON_KWARGS)
    assert isinstance(prompt, str)
    assert len(prompt) > 50


def test_general_purpose_contains_key_directives():
    prompt = build_system_prompt("general-purpose", enable_thinking=False, **COMMON_KWARGS)
    assert "tool" in prompt.lower()
    assert "Atri" in prompt


def test_agent_v3_mentions_tool_compliance():
    prompt = build_system_prompt("agent-v3", enable_thinking=False, **COMMON_KWARGS)
    assert "exact_text_to_replace" in prompt


def test_thinking_prefix_NOT_injected_manually():
    """<|think|> must NOT appear in the prompt string — template handles it."""
    for profile in VALID_PROMPT_PROFILES:
        prompt = build_system_prompt(profile, enable_thinking=True, **COMMON_KWARGS)
        assert "<|think|>" not in prompt, (
            f"Profile '{profile}' manually injects <|think|> — template should own this"
        )


def test_normalize_valid_profile():
    assert normalize_prompt_profile("general-purpose") == "general-purpose"
    assert normalize_prompt_profile("  Agent-V3  ") == "agent-v3"


def test_normalize_invalid_profile_raises():
    with pytest.raises(ValueError, match="Unsupported"):
        normalize_prompt_profile("nonexistent-profile")


def test_normalize_empty_defaults_to_general_purpose():
    assert normalize_prompt_profile("") == "general-purpose"
    assert normalize_prompt_profile(None) == "general-purpose"
