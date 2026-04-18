"""Hook framework for orchestrator lifecycle and policy events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List


HookCallback = Callable[[Dict[str, Any]], None]


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
            except Exception:
                # Hooks must never block main execution.
                continue

    def recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        if limit <= 0:
            return []
        return self._history[-limit:]
