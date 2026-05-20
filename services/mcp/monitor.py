"""
File watch / monitor mode for atri-cli MCP server.
Uses inotify (Linux) via watchdog library if available, falls back to polling.
Inspired by Pi's monitor mode with event history.
"""
from __future__ import annotations

import logging
import os
import time
import threading
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Try watchdog for inotify-based watching
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileSystemEvent
    _WATCHDOG_AVAILABLE = True
except ImportError:
    _WATCHDOG_AVAILABLE = False


class FileWatcher:
    """
    Watches a file or directory for changes.
    Calls callback(event_dict) on each change.
    """

    def __init__(
        self,
        path: str,
        callback: Callable[[dict], None],
        pattern: Optional[str] = None,
        poll_interval: float = 1.0,
    ):
        self.path = Path(path)
        self.callback = callback
        self.pattern = pattern
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._event_history: list[dict] = []

    def start(self) -> None:
        if _WATCHDOG_AVAILABLE:
            self._start_watchdog()
        else:
            self._start_polling()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)

    def get_history(self) -> list[dict]:
        return list(self._event_history)

    def _record(self, event: dict) -> None:
        self._event_history.append(event)
        if len(self._event_history) > 100:
            self._event_history = self._event_history[-100:]
        try:
            self.callback(event)
        except Exception as e:
            logger.warning("File watcher callback failed: %s", e)

    def _start_polling(self) -> None:
        """Poll-based fallback using mtime."""
        def _poll_loop() -> None:
            mtimes: dict[str, float] = {}

            def _scan() -> Optional[dict]:
                p = self.path
                paths = [p] if p.is_file() else list(p.rglob(self.pattern or "*"))
                for fp in paths:
                    if fp.is_file():
                        try:
                            mtime = fp.stat().st_mtime
                            key = str(fp)
                            if key in mtimes:
                                if mtime != mtimes[key]:
                                    mtimes[key] = mtime
                                    return {"type": "modified", "path": str(fp), "ts": time.time()}
                            else:
                                mtimes[key] = mtime
                        except OSError:
                            pass
                return None

            while not self._stop_event.is_set():
                event = _scan()
                if event:
                    self._record(event)
                self._stop_event.wait(timeout=self.poll_interval)

        self._thread = threading.Thread(target=_poll_loop, daemon=True)
        self._thread.start()

    def _start_watchdog(self) -> None:
        """Watchdog (inotify on Linux) based watching."""
        parent = self

        class _Handler(FileSystemEventHandler):  # type: ignore[misc]
            def on_any_event(self, event: "FileSystemEvent") -> None:
                import fnmatch
                if event.is_directory:
                    return
                if parent.pattern and not fnmatch.fnmatch(
                    os.path.basename(event.src_path), parent.pattern
                ):
                    return
                ev = {
                    "type": event.event_type,
                    "path": event.src_path,
                    "ts": time.time(),
                }
                parent._record(ev)

        observer = Observer()
        watch_path = str(self.path.parent if self.path.is_file() else self.path)
        observer.schedule(_Handler(), watch_path, recursive=not self.path.is_file())
        observer.start()

        def _run() -> None:
            try:
                while not self._stop_event.is_set():
                    self._stop_event.wait(timeout=0.5)
            finally:
                observer.stop()
                observer.join()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()


# Global registry of active watchers
_WATCHERS: dict[str, FileWatcher] = {}


def start_watch(
    watch_id: str,
    path: str,
    callback: Callable[[dict], None],
    pattern: Optional[str] = None,
) -> FileWatcher:
    """Start a file watcher with the given ID. Stops any existing watcher with the same ID."""
    stop_watch(watch_id)
    watcher = FileWatcher(path, callback, pattern)
    watcher.start()
    _WATCHERS[watch_id] = watcher
    return watcher


def stop_watch(watch_id: str) -> bool:
    """Stop a file watcher. Returns True if it existed."""
    watcher = _WATCHERS.pop(watch_id, None)
    if watcher:
        watcher.stop()
        return True
    return False


def list_watches() -> list[dict[str, Any]]:
    """Return a summary of all active watchers."""
    return [
        {
            "id": wid,
            "path": str(w.path),
            "pattern": w.pattern,
            "events": len(w.get_history()),
        }
        for wid, w in _WATCHERS.items()
    ]
