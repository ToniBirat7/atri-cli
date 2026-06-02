"""Hook framework for orchestrator lifecycle and policy events.

Provides two hook systems:
1. HookManager — lightweight in-process event bus used by api.py for lifecycle events.
2. HookRegistry — beforeToolCall/afterToolCall interceptors for the agent loop.
   Inspired by Pi's beforeToolCall/afterToolCall + Gemini's ConfirmationBus.
   Hooks intercept tool calls for: validation, path protection, caching, approval gates.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List

__all__ = [
    "BLOCK",
    "HookCallback",
    "HookFn",
    "HookManager",
    "HookRegistry",
    "hook_registry",
    "register_builtin_hooks",
    "add_allowed_write_path",
]

logger = logging.getLogger(__name__)

# ── Phase 5.3: Governance File Protection — per-session allowed-path whitelist ─
_ALLOWED_WRITE_PATHS: set[str] = set()


def add_allowed_write_path(path: str) -> None:
    """Register a path prefix that bypasses governance protection."""
    _ALLOWED_WRITE_PATHS.add(os.path.abspath(path))
# ──────────────────────────────────────────────────────────────────────────────

HookCallback = Callable[[Dict[str, Any]], None]

# ── HookRegistry sentinel ──────────────────────────────────────────────────────

# Return BLOCK from a before-hook to cancel the tool call.
BLOCK = "__HOOK_BLOCK__"

HookFn = Callable[..., Any]  # sync or async


@dataclass
class HookManager:
    """Lightweight in-process hook manager with event history."""

    enabled: bool = True
    _callbacks: Dict[str, List[HookCallback]] = field(default_factory=dict)
    _history: List[Dict[str, Any]] = field(default_factory=list)

    def register(self, event_name: str, callback: HookCallback) -> None:
        self._callbacks.setdefault(event_name, []).append(callback)

    def emit(self, event_name: str, payload: Dict[str, Any]) -> None:
        if not self.enabled:
            return

        event = {"event": event_name, "payload": dict(payload)}
        self._history.append(event)

        for callback in self._callbacks.get(event_name, []):
            try:
                callback(payload)
            except Exception as e:
                # Hooks must never block main execution.
                logger.warning("HookManager callback %s raised: %s", getattr(callback, "__name__", callback), e, exc_info=True)
                continue

    def recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        if limit <= 0:
            return []
        return self._history[-limit:]


# ── HookRegistry ───────────────────────────────────────────────────────────────


class HookRegistry:
    """Registry for beforeToolCall and afterToolCall hooks."""

    def __init__(self) -> None:
        self._before: List[HookFn] = []
        self._after: List[HookFn] = []

    def before(self, fn: HookFn) -> HookFn:
        """Register a beforeToolCall hook. Can be used as a decorator or called directly."""
        self._before.append(fn)
        return fn

    def after(self, fn: HookFn) -> HookFn:
        """Register an afterToolCall hook."""
        self._after.append(fn)
        return fn

    async def run_before(self, tool_name: str, tool_input: dict) -> tuple:
        """
        Run all before hooks. Returns (modified_input_or_BLOCK, error_message | None).
        If any hook returns BLOCK or raises, the tool call is cancelled.
        """
        current_input = dict(tool_input)
        for hook in self._before:
            try:
                result = hook(tool_name, current_input)
                if asyncio.iscoroutine(result):
                    result = await result
                if result is BLOCK or result == BLOCK:
                    return BLOCK, "Tool call blocked by hook"
                if isinstance(result, dict):
                    current_input = result
                elif result is None:
                    pass  # hook did not modify input
            except Exception as exc:
                logger.warning("Before hook %s failed: %s", getattr(hook, "__name__", hook), exc)
        return current_input, None

    async def run_after(self, tool_name: str, tool_input: dict, result: Any) -> Any:
        """Run all after hooks. Returns potentially modified result."""
        current_result = result
        for hook in self._after:
            try:
                modified = hook(tool_name, tool_input, current_result)
                if asyncio.iscoroutine(modified):
                    modified = await modified
                if modified is not None:
                    current_result = modified
            except Exception as exc:
                logger.warning("After hook %s failed: %s", getattr(hook, "__name__", hook), exc)
        return current_result


# ── Global singleton ───────────────────────────────────────────────────────────

# Shared HookRegistry — imported by AgentLoop; hooks are registered at startup.
hook_registry = HookRegistry()


def register_builtin_hooks(registry: HookRegistry, permission_mode: str = "default") -> None:
    """Register the default built-in hooks onto *registry*."""

    @registry.before
    def governance_file_protection(tool_name: str, tool_input: dict):
        """Block writes to sensitive files: .git/, .env*, .ssh/, private keys."""
        WRITE_TOOLS = {
            "write_file", "edit_file", "edit_diff",
            "append_file", "delete_path", "move_file",
        }
        if tool_name not in WRITE_TOOLS:
            return tool_input

        path = (
            tool_input.get("target_file_path")
            or tool_input.get("target_path")
            or tool_input.get("source_path")
            or ""
        )
        if not path:
            return tool_input

        # Phase 5.3: skip blocking if path is within an allowed-path prefix
        abs_path = os.path.abspath(str(path))
        for allowed in _ALLOWED_WRITE_PATHS:
            if abs_path.startswith(allowed):
                return tool_input

        # Phase 5.3: warn-only patterns — log but do not block
        WARN_PATTERNS = [
            r"(^|[\\/])\.gitignore$",
            r"\.lock$",
            r"(^|[\\/])Makefile$",
        ]
        for pat in WARN_PATTERNS:
            if re.search(pat, str(path)):
                logger.warning(
                    "Hook warning: write to semi-sensitive path: %s (tool: %s)", path, tool_name
                )
                return tool_input

        p = Path(abs_path)
        # Block if any path component is exactly ".git" or ".ssh"
        if ".git" in p.parts or ".ssh" in p.parts:
            logger.warning(
                "Hook blocked write to sensitive path: %s (tool: %s)", path, tool_name
            )
            return BLOCK
        # Block .env* files anywhere in the path
        if p.name.startswith(".env"):
            logger.warning(
                "Hook blocked write to sensitive path: %s (tool: %s)", path, tool_name
            )
            return BLOCK
        # Block private key files (id_rsa, id_ed25519, etc.)
        if p.name in ("id_rsa", "id_ed25519") or p.name.startswith("id_rsa") or p.name.startswith("id_ed25519"):
            logger.warning(
                "Hook blocked write to sensitive path: %s (tool: %s)", path, tool_name
            )
            return BLOCK
        return tool_input
