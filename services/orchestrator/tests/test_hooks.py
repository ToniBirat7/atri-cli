from __future__ import annotations

from hooks import HookManager


def test_hook_manager_emits_to_registered_callbacks():
    manager = HookManager(enabled=True)
    captured = []

    manager.register("PreToolUse", lambda payload: captured.append(payload.get("tool_name")))
    manager.emit("PreToolUse", {"tool_name": "read_file"})

    assert captured == ["read_file"]
    assert manager.recent_events(1)[0]["event"] == "PreToolUse"


def test_hook_manager_callback_failure_isolated():
    manager = HookManager(enabled=True)
    captured = []

    def _boom(_payload):
        raise RuntimeError("hook failed")

    manager.register("Notification", _boom)
    manager.register("Notification", lambda payload: captured.append(payload.get("level")))
    manager.emit("Notification", {"level": "error"})

    assert captured == ["error"]


def test_hook_manager_disabled_skips_events():
    manager = HookManager(enabled=False)
    manager.emit("PreToolUse", {"tool_name": "write_file"})
    assert manager.recent_events() == []
