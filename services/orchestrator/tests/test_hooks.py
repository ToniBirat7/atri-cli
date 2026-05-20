"""
Tests for services/orchestrator/hooks.py
"""
import logging
import sys
from pathlib import Path
import pytest
import pytest_asyncio

_ORCH_DIR = Path(__file__).resolve().parent.parent
if str(_ORCH_DIR) not in sys.path:
    sys.path.insert(0, str(_ORCH_DIR))

from hooks import HookRegistry, BLOCK, register_builtin_hooks


# ── HookRegistry.run_before — basic BLOCK sentinel ─────────────────────────────

@pytest.mark.asyncio
async def test_before_hook_returns_block_cancels_call():
    registry = HookRegistry()

    @registry.before
    def blocking_hook(tool_name, tool_input):
        return BLOCK

    result, err = await registry.run_before("write_file", {"target_file_path": "/tmp/x.txt"})
    assert result is BLOCK


@pytest.mark.asyncio
async def test_before_hook_can_modify_input():
    registry = HookRegistry()

    @registry.before
    def add_field(tool_name, tool_input):
        return {**tool_input, "extra": "injected"}

    result, err = await registry.run_before("read_file", {"path": "/tmp/foo.txt"})
    assert result.get("extra") == "injected"
    assert err is None


@pytest.mark.asyncio
async def test_before_hook_passthrough_when_no_match():
    registry = HookRegistry()
    register_builtin_hooks(registry)

    # read_text_file is not a write tool — should pass through unchanged
    tool_input = {"target_file_path": "/tmp/safe.txt"}
    result, err = await registry.run_before("read_text_file", tool_input)
    assert result == tool_input
    assert err is None


# ── Path pattern matching ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_git_dir_blocked():
    registry = HookRegistry()
    register_builtin_hooks(registry)

    result, err = await registry.run_before(
        "write_file",
        {"target_file_path": ".git/config"},
    )
    assert result is BLOCK


@pytest.mark.asyncio
async def test_gitignore_not_blocked():
    """
    .gitignore is a warn-only path — it should NOT be blocked; the hook returns
    the input unchanged after logging a warning.
    """
    registry = HookRegistry()
    register_builtin_hooks(registry)

    result, err = await registry.run_before(
        "write_file",
        {"target_file_path": ".gitignore"},
    )
    # .gitignore hits the WARN_PATTERNS branch, so result should be the input dict (not BLOCK)
    assert result is not BLOCK
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_env_file_blocked():
    registry = HookRegistry()
    register_builtin_hooks(registry)

    result, err = await registry.run_before(
        "edit_file",
        {"target_file_path": "services/orchestrator/.env"},
    )
    assert result is BLOCK


# ── Hook failures are logged, not silently swallowed ───────────────────────────

@pytest.mark.asyncio
async def test_before_hook_failure_is_logged_not_raised(caplog):
    registry = HookRegistry()

    @registry.before
    def bad_hook(tool_name, tool_input):
        raise RuntimeError("intentional hook failure")

    with caplog.at_level(logging.WARNING, logger="hooks"):
        # Should NOT raise — bad hook is caught and logged
        result, err = await registry.run_before("read_file", {"path": "/tmp/ok.txt"})

    assert "intentional hook failure" in caplog.text
    # The call should still succeed (pass-through) after the bad hook
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_after_hook_failure_is_logged_not_raised(caplog):
    registry = HookRegistry()

    @registry.after
    def bad_after_hook(tool_name, tool_input, result):
        raise ValueError("after hook boom")

    with caplog.at_level(logging.WARNING, logger="hooks"):
        result = await registry.run_after("read_file", {}, "original result")

    assert "after hook boom" in caplog.text
    # Original result preserved when after hook raises
    assert result == "original result"
