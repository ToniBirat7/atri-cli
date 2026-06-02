"""
Production-grade local filesystem MCP server.

Design goals:
- Claude Desktop-like filesystem capabilities for local workflows
- Strict directory sandboxing (allow-list roots only)
- Path traversal and symlink escape protection
- Safe defaults for destructive operations
"""

from __future__ import annotations

import fnmatch
import importlib.util
import json
import logging
"""
Atri Code MCP Server - Model Context Protocol Implementation.

This module exposes a suite of tools to the LLM orchestrator:
- Filesystem: read, write, edit, list, search files.
- Utilities: command execution, environment info.
- Search: web search via adapters (Tavily, etc).

Built using the FastMCP framework for high-performance tool dispatch.
"""

import os
import pty
import re
import select
import shutil
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from .search_adapter import fetch_web_content, search_web_results
except ImportError:
    try:
        from search_adapter import fetch_web_content, search_web_results
    except ImportError:
        # Support in-process loading via importlib without package context.
        adapter_path = Path(__file__).with_name("search_adapter.py")
        spec = importlib.util.spec_from_file_location("atri_search_adapter", str(adapter_path))
        if spec is None or spec.loader is None:
            raise
        module = importlib.util.module_from_spec(spec)
        sys.modules.setdefault("atri_search_adapter", module)
        spec.loader.exec_module(module)
        fetch_web_content = module.fetch_web_content
        search_web_results = module.search_web_results

try:
    from .hashline import encode_file as _encode_file, apply_hashline_edits as _apply_hashline_edits, HashMismatchError as _HashMismatchError
except ImportError:
    try:
        from hashline import encode_file as _encode_file, apply_hashline_edits as _apply_hashline_edits, HashMismatchError as _HashMismatchError  # type: ignore[no-redef]
    except ImportError:
        import importlib.util as _ilu
        _hl_path = Path(__file__).parent.parent / "orchestrator" / "hashline.py"
        if _hl_path.exists():
            _hl_spec = _ilu.spec_from_file_location("hashline", str(_hl_path))
            if _hl_spec and _hl_spec.loader:
                _hl_mod = _ilu.module_from_spec(_hl_spec)
                _hl_spec.loader.exec_module(_hl_mod)
                _encode_file = _hl_mod.encode_file
                _apply_hashline_edits = _hl_mod.apply_hashline_edits
                _HashMismatchError = _hl_mod.HashMismatchError
            else:
                _encode_file = None  # type: ignore[assignment]
                _apply_hashline_edits = None  # type: ignore[assignment]
                _HashMismatchError = None  # type: ignore[assignment]
        else:
            _encode_file = None  # type: ignore[assignment]
            _apply_hashline_edits = None  # type: ignore[assignment]
            _HashMismatchError = None  # type: ignore[assignment]

try:
    from .diff_engine import DiffEngine
except (ImportError, ValueError):
    try:
        from diff_engine import DiffEngine
    except ImportError:
        # Fallback for dynamic loading: try to find it in the same directory
        import importlib.util
        _engine_path = Path(__file__).parent / "diff_engine.py"
        if _engine_path.exists():
            _spec = importlib.util.spec_from_file_location("diff_engine", str(_engine_path))
            if _spec and _spec.loader:
                _mod = importlib.util.module_from_spec(_spec)
                _spec.loader.exec_module(_mod)
                DiffEngine = _mod.DiffEngine
        else:
            class DiffEngine:
                @staticmethod
                def apply_diff(path: str, diff: str) -> bool:
                    raise RuntimeError("DiffEngine not available. Unified diffs cannot be applied.")

try:
    from fastmcp import FastMCP
except ImportError:
    class FastMCP:  # type: ignore[override]
        """Fallback shim for in-process imports when fastmcp isn't installed."""

        def __init__(self, name: str):
            self.name = name

        def tool(self, fn=None, **_kwargs):
            if fn is None:
                def decorator(inner):
                    return inner
                return decorator
            return fn

        def run(self):
            raise RuntimeError(
                "fastmcp is required to run this server process. "
                "Install fastmcp in the runtime environment."
            )


LOGGER = logging.getLogger("atri.mcp.filesystem")


def _configure_mcp_logging() -> None:
    """Configure MCP server logging. Called explicitly at server startup, not at import time (C.5)."""
    logging.basicConfig(level=os.getenv("MCP_LOG_LEVEL", "INFO"))


def _load_allowed_dirs() -> list[Path]:
    """
    Load allowed directories from env var MCP_ALLOWED_DIRS.

    Format: os.pathsep-separated list, e.g.:
    - Linux/macOS: /path/one:/path/two
    - Windows: C:\\path\\one;D:\\path\\two
    """
    raw = os.getenv("MCP_ALLOWED_DIRS", "").strip()
    if raw:
        candidates = [p.strip() for p in raw.split(os.pathsep) if p.strip()]
    else:
        # Safe local default: repository root (two levels up from services/mcp)
        repo_root = Path(__file__).resolve().parents[2]
        candidates = [str(repo_root)]

    resolved: list[Path] = []
    for item in candidates:
        p = Path(item).expanduser().resolve()
        if p.exists() and p.is_dir():
            resolved.append(p)
        else:
            LOGGER.warning("Ignoring invalid allowed directory: %s", item)

    if not resolved:
        raise RuntimeError(
            "No valid allowed directories configured. "
            "Set MCP_ALLOWED_DIRS to one or more existing directories."
        )

    return resolved


_INITIAL_ALLOWED_DIRS_CACHE: list[Path] | None = None


def _get_initial_allowed_dirs() -> list[Path]:
    """Lazy singleton for INITIAL_ALLOWED_DIRS — deferred until first access (C.5)."""
    global _INITIAL_ALLOWED_DIRS_CACHE
    if _INITIAL_ALLOWED_DIRS_CACHE is None:
        _INITIAL_ALLOWED_DIRS_CACHE = _load_allowed_dirs()
    return _INITIAL_ALLOWED_DIRS_CACHE


# Eagerly resolved on first import for backward compatibility with call sites that
# reference INITIAL_ALLOWED_DIRS directly.  The actual load is deferred via the
# lazy helper so that module import does not raise when MCP_ALLOWED_DIRS is unset
# in non-server contexts (e.g. unit tests, orchestrator in-process import).
INITIAL_ALLOWED_DIRS: list[Path] = []  # populated on first server start via _get_initial_allowed_dirs()
MAX_READ_BYTES = int(os.getenv("MCP_MAX_READ_BYTES", "1048576"))  # 1 MiB
MAX_WRITE_BYTES = int(os.getenv("MCP_MAX_WRITE_BYTES", "1048576"))  # 1 MiB
MAX_SEARCH_RESULTS = int(os.getenv("MCP_MAX_SEARCH_RESULTS", "200"))
MAX_WEB_SEARCH_RESULTS = int(os.getenv("MCP_MAX_WEB_SEARCH_RESULTS", "8"))
MAX_FETCH_CHARS = int(os.getenv("MCP_MAX_FETCH_CHARS", "12000"))
ALLOW_HIDDEN = os.getenv("MCP_ALLOW_HIDDEN", "false").lower() == "true"


class _RuntimePolicy:
    def __init__(self, allowed_dirs: list[Path]):
        self._lock = threading.RLock()
        self._allowed_dirs = list(allowed_dirs)

    def get_allowed_dirs(self) -> list[Path]:
        with self._lock:
            return list(self._allowed_dirs)

    def set_allowed_dirs(self, dirs: list[Path]) -> None:
        with self._lock:
            self._allowed_dirs = list(dirs)


def _initialize_server() -> None:
    """Perform all startup side effects (C.5): logging config + allowed-dirs resolution."""
    global INITIAL_ALLOWED_DIRS
    _configure_mcp_logging()
    INITIAL_ALLOWED_DIRS = _get_initial_allowed_dirs()
    POLICY.set_allowed_dirs(INITIAL_ALLOWED_DIRS)


POLICY = _RuntimePolicy([])  # starts empty; populated by _initialize_server() at first use

mcp = FastMCP("Atri Code MCP")

# C.5: Trigger server initialization when the module is loaded as an entry point
# (fastmcp run main.py:mcp) without going through __main__.  The call is idempotent
# — repeated imports are safe because _get_initial_allowed_dirs() caches its result.
_initialize_server()


def _is_under_allowed_dirs(path: Path) -> bool:
    for root in POLICY.get_allowed_dirs():
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _has_hidden_component(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts if part not in (".", ".."))


def _resolve_user_path(user_path: str) -> Path:
    if "\x00" in user_path:
        raise ValueError("Invalid path: null byte is not allowed")

    raw = Path(user_path).expanduser()
    allowed_dirs = POLICY.get_allowed_dirs()
    if not allowed_dirs:
        raise RuntimeError("No allowed directories configured")

    target = raw if raw.is_absolute() else (allowed_dirs[0] / raw)
    resolved = target.resolve(strict=False)

    if not _is_under_allowed_dirs(resolved):
        raise PermissionError(
            f"Access denied for path '{user_path}'. "
            "Path is outside allowed directories."
        )

    if not ALLOW_HIDDEN:
        # Only check for hidden components in the path *relative* to the allowed dir.
        # The allowed dir itself may live under ~/.local or similar — that's pre-approved
        # by configuration and should not block access to files within it.
        for root in POLICY.get_allowed_dirs():
            try:
                relative = resolved.relative_to(root)
                if _has_hidden_component(relative):
                    raise PermissionError(
                        f"Access denied for hidden path '{user_path}'. "
                        "Set MCP_ALLOW_HIDDEN=true to allow hidden files/directories."
                    )
                break
            except ValueError:
                continue

    return resolved


def _to_relative_display(path: Path) -> str:
    for root in POLICY.get_allowed_dirs():
        try:
            return str(path.relative_to(root))
        except ValueError:
            continue
    return str(path)


def _validate_directories(paths: list[str]) -> list[Path]:
    if not paths:
        raise ValueError("At least one directory must be provided")

    resolved: list[Path] = []
    for item in paths:
        p = Path(item).expanduser().resolve()
        if not p.exists() or not p.is_dir():
            raise ValueError(f"Invalid directory: {item}")
        resolved.append(p)
    return resolved


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _read_text(path: Path) -> str:
    size = path.stat().st_size
    if size > MAX_READ_BYTES:
        raise ValueError(
            f"File too large to read safely ({size} bytes). "
            f"Limit is {MAX_READ_BYTES} bytes."
        )
    return path.read_text(encoding="utf-8", errors="replace")


@mcp.tool
def list_allowed_directories() -> list[str]:
    """List directories this MCP server can access."""
    return [str(p) for p in POLICY.get_allowed_dirs()]


@mcp.tool
def set_allowed_directory(target_directory_path: str) -> dict[str, Any]:
    """
    Set a single active allowed directory at runtime.

    Intended for user-selected workspace roots from frontend/orchestrator.
    """
    validated = _validate_directories([target_directory_path])
    POLICY.set_allowed_dirs(validated)
    return {
        "ok": True,
        "active_allowed_directory": str(validated[0]),
        "allowed_directories": [str(validated[0])],
    }


@mcp.tool
def set_allowed_directories(paths: list[str]) -> dict[str, Any]:
    """Set multiple active allowed directories at runtime."""
    validated = _validate_directories(paths)
    POLICY.set_allowed_dirs(validated)
    return {
        "ok": True,
        "allowed_directories": [str(p) for p in validated],
    }


@mcp.tool
def reset_allowed_directories() -> dict[str, Any]:
    """Reset allowed directories back to initial startup configuration."""
    POLICY.set_allowed_dirs(INITIAL_ALLOWED_DIRS)
    return {
        "ok": True,
        "allowed_directories": [str(p) for p in POLICY.get_allowed_dirs()],
    }


@mcp.tool
def list_directory(target_path: str = ".") -> dict[str, Any]:
    """List immediate directory contents."""
    directory = _resolve_user_path(target_path)
    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {target_path}")
    if not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {target_path}")

    entries: list[dict[str, Any]] = []
    for item in sorted(directory.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if not ALLOW_HIDDEN and item.name.startswith("."):
            continue
        stat = item.stat()
        entries.append(
            {
                "name": item.name,
                "path": _to_relative_display(item),
                "type": "directory" if item.is_dir() else "file",
                "size": stat.st_size if item.is_file() else None,
                "modified_at": _iso(stat.st_mtime),
            }
        )

    return {
        "path": _to_relative_display(directory),
        "entries": entries,
        "count": len(entries),
    }


def _build_tree(path: Path, depth: int) -> dict[str, Any]:
    node = {
        "name": path.name,
        "path": _to_relative_display(path),
        "type": "directory" if path.is_dir() else "file",
    }
    if not path.is_dir() or depth <= 0:
        return node

    children: list[dict[str, Any]] = []
    for item in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if not ALLOW_HIDDEN and item.name.startswith("."):
            continue
        children.append(_build_tree(item, depth - 1))
    node["children"] = children
    return node


@mcp.tool
def directory_tree(target_path: str = ".", max_depth: int = 4) -> dict[str, Any]:
    """Return a recursive JSON tree of directories/files."""
    if max_depth < 1 or max_depth > 12:
        raise ValueError("max_depth must be between 1 and 12")
    root = _resolve_user_path(target_path)
    if not root.exists():
        raise FileNotFoundError(f"Path not found: {target_path}")
    return _build_tree(root, max_depth)


@mcp.tool
def read_text_file(
    target_file_path: str,
    head: int | None = None,
    tail: int | None = None,
    hashline: bool = False,
) -> dict[str, Any]:
    """
    Read UTF-8 text content from a file.
    REQUIRED: 'target_file_path' is the path to the file.

    Optional slicing:
    - head: first N lines
    - tail: last N lines

    Optional hash-anchoring:
    - hashline: if True, return content annotated with line-hash anchors
      (format: 'LINENUM#HASH|TEXT') suitable for use with edit_file_hashline.
    """
    if head is not None and tail is not None:
        raise ValueError("Specify only one of head or tail")

    file_path = _resolve_user_path(target_file_path)
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"File not found: {target_file_path}")

    content = _read_text(file_path)
    lines = content.splitlines()

    if head is not None:
        if head < 0:
            raise ValueError("head must be >= 0")
        lines = lines[:head]
    elif tail is not None:
        if tail < 0:
            raise ValueError("tail must be >= 0")
        lines = lines[-tail:] if tail > 0 else []

    final = "\n".join(lines)

    if hashline:
        if _encode_file is None:
            return {
                "path": _to_relative_display(file_path),
                "content": final,
                "line_count": len(lines),
                "hashline": False,
                "error": "hashline module not available",
            }
        final = _encode_file(final)
        return {
            "path": _to_relative_display(file_path),
            "content": final,
            "line_count": len(lines),
            "hashline": True,
        }

    return {
        "path": _to_relative_display(file_path),
        "content": final,
        "line_count": len(lines),
    }


@mcp.tool
def read_file(target_file_path: str, start_line: int = 1, end_line: int = 200) -> dict[str, Any]:
    """
    Backward-compatible alias for line-ranged file reads.

    This keeps compatibility with clients that call `read_file` while
    internally reusing the `read_text_file` implementation.
    """
    if start_line < 1:
        raise ValueError("start_line must be >= 1")
    if end_line < start_line:
        raise ValueError("end_line must be >= start_line")

    payload = read_text_file(target_file_path=target_file_path)
    lines = str(payload.get("content", "")).splitlines()
    sliced = lines[start_line - 1 : end_line]
    return {
        "path": payload.get("path"),
        "content": "\n".join(sliced),
        "start_line": start_line,
        "end_line": end_line,
        "line_count": len(sliced),
    }


@mcp.tool
def read_multiple_files(paths: list[str]) -> dict[str, Any]:
    """Read multiple text files; failures are captured per file."""
    results: list[dict[str, Any]] = []
    for p in paths:
        try:
            result = read_text_file(target_file_path=p)
            results.append({"path": p, "ok": True, "result": result})
        except Exception as exc:
            results.append({"path": p, "ok": False, "error": str(exc)})
    return {"results": results}


@mcp.tool
def get_file_info(target_path: str) -> dict[str, Any]:
    """Get metadata for a file or directory."""
    target = _resolve_user_path(target_path)
    if not target.exists():
        raise FileNotFoundError(f"Path not found: {target_path}")

    stat = target.stat()
    return {
        "path": _to_relative_display(target),
        "type": "directory" if target.is_dir() else "file",
        "size": stat.st_size,
        "created_at": _iso(stat.st_ctime),
        "modified_at": _iso(stat.st_mtime),
        "accessed_at": _iso(stat.st_atime),
        "permissions": oct(stat.st_mode & 0o777),
    }


@mcp.tool
def create_directory(target_directory_path: str) -> dict[str, Any]:
    """Create directory recursively; succeeds if it already exists."""
    target = _resolve_user_path(target_directory_path)
    target.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "path": _to_relative_display(target)}


@mcp.tool
def write_file(target_file_path: str, content: str, overwrite: bool = True) -> dict[str, Any]:
    """
    Write text to file (UTF-8).
    REQUIRED: 'target_file_path' is the path to the file.
    REQUIRED: 'content' is the text to write.

    Safety:
    - Refuses writes larger than MCP_MAX_WRITE_BYTES
    - Atomic replace through temp file
    """
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_WRITE_BYTES:
        raise ValueError(
            f"Content too large to write safely ({len(encoded)} bytes). "
            f"Limit is {MAX_WRITE_BYTES} bytes."
        )

    target = _resolve_user_path(target_file_path)
    if target.exists() and not overwrite:
        raise FileExistsError(f"File already exists and overwrite=false: {target_file_path}")

    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(content, encoding="utf-8")
    temp.replace(target)

    return {
        "ok": True,
        "path": _to_relative_display(target),
        "bytes_written": len(encoded),
    }


@mcp.tool
def append_file(target_file_path: str, content: str) -> dict[str, Any]:
    """Append UTF-8 text to an existing or new file."""
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_WRITE_BYTES:
        raise ValueError(
            f"Content too large to append safely ({len(encoded)} bytes). "
            f"Limit is {MAX_WRITE_BYTES} bytes."
        )

    target = _resolve_user_path(target_file_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fp:
        fp.write(content)

    return {
        "ok": True,
        "path": _to_relative_display(target),
"bytes_appended": len(encoded),
    }


@mcp.tool
def edit_file(
    target_file_path: Optional[str] = None,
    exact_text_to_replace: Optional[str] = None,
    new_text_content: Optional[str] = None,
    dry_run: bool = False,
    # Alias params: small models (Gemma 4 E2B) cannot reliably reproduce the
    # canonical names, so accept every common variant. All are OPTIONAL in the
    # schema — a wrong-but-recognised name still resolves instead of failing
    # schema validation before the body runs (the old bug). Canonical wins.
    old_text: Optional[str] = None,
    old_string: Optional[str] = None,
    new_text: Optional[str] = None,
    replacement_text: Optional[str] = None,
    new_string: Optional[str] = None,
    content: Optional[str] = None,
    path: Optional[str] = None,
    file_path: Optional[str] = None,
) -> dict[str, Any]:
    """
    Replace an exact block of text in a file.

    REQUIRED: 'target_file_path' — path to the file (aliases: path, file_path).
    REQUIRED: 'exact_text_to_replace' — the EXACT text to find (aliases: old_text, old_string).
    REQUIRED: 'new_text_content' — the replacement text (aliases: new_text, replacement_text, new_string, content).
    """
    # Resolve field aliases. Canonical names take priority; first non-empty alias wins.
    def _first(*values: Optional[str]) -> Optional[str]:
        for v in values:
            if v is not None and v != "":
                return v
        return None

    _path = _first(target_file_path, path, file_path)
    _old_text = _first(exact_text_to_replace, old_text, old_string)
    # new text may legitimately be empty (deletion), so treat "" as provided.
    _new_candidates = [new_text_content, new_text, replacement_text, new_string, content]
    _new_text = next((v for v in _new_candidates if v is not None), None)

    if not _path:
        raise ValueError(
            "Missing required argument 'target_file_path' (path to the file). "
            "Accepted aliases: path, file_path."
        )
    if _old_text is None:
        raise ValueError(
            "Missing required argument 'exact_text_to_replace' (the exact text to find). "
            "Accepted aliases: old_text, old_string."
        )
    if _new_text is None:
        raise ValueError(
            "Missing required argument 'new_text_content' (the replacement text). "
            "Accepted aliases: new_text, replacement_text, new_string, content."
        )

    if _old_text == "":
        raise ValueError("exact_text_to_replace cannot be empty")

    target = _resolve_user_path(_path)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"File not found: {_path}")

    original = _read_text(target)
    count = original.count(_old_text)
    if count == 0:
        raise ValueError("exact_text_to_replace not found in file")

    updated = original.replace(_old_text, _new_text)
    delta = len(updated.encode("utf-8")) - len(original.encode("utf-8"))

    if dry_run:
        return {
            "ok": True,
            "path": _to_relative_display(target),
            "matches": count,
            "byte_delta": delta,
            "applied": False,
        }

    write_file(target_file_path=_path, content=updated, overwrite=True)
    return {
        "ok": True,
        "path": _to_relative_display(target),
        "matches": count,
        "byte_delta": delta,
        "applied": True,
    }


@mcp.tool
def move_file(source_path: str, destination_path: str, overwrite: bool = False) -> dict[str, Any]:
    """Move or rename file/directory within allowed directories."""
    src = _resolve_user_path(source_path)
    dst = _resolve_user_path(destination_path)

    if not src.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")
    if dst.exists() and not overwrite:
        raise FileExistsError(f"Destination exists and overwrite=false: {destination_path}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and overwrite:
        if dst.is_dir() and not src.is_dir():
            raise IsADirectoryError("Cannot overwrite directory with file")
        if dst.is_file() and src.is_dir():
            raise NotADirectoryError("Cannot overwrite file with directory")
        if dst.is_dir():
            shutil.rmtree(dst)
        else:
            dst.unlink()

    src.replace(dst)
    return {
        "ok": True,
        "source": _to_relative_display(src),
        "destination": _to_relative_display(dst),
    }


@mcp.tool
def delete_path(target_path: str, recursive: bool = False) -> dict[str, Any]:
    """
    Delete a file or directory.
    Safety:
    - directories require recursive=true
    """
    target = _resolve_user_path(target_path)
    if not target.exists():
        raise FileNotFoundError(f"Path not found: {target_path}")

    if target.is_dir():
        if not recursive:
            raise ValueError("Refusing to delete directory without recursive=true")
        shutil.rmtree(target)
    else:
        target.unlink()

    return {"ok": True, "deleted": _to_relative_display(target)}


@mcp.tool
def search_files(
    pattern: str,
    target_path: str = ".",
    exclude_patterns: list[str] | None = None,
    max_results: int = MAX_SEARCH_RESULTS,
) -> dict[str, Any]:
    """
    Recursively search by glob-style filename pattern.

    Example patterns:
    - *.py
    - *config*
    """
    if max_results < 1:
        raise ValueError("max_results must be >= 1")
    max_results = min(max_results, MAX_SEARCH_RESULTS)

    root = _resolve_user_path(target_path)
    if not root.exists() or not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {target_path}")

    excludes = exclude_patterns or []
    matches: list[str] = []

    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        if not ALLOW_HIDDEN:
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]

        for name in filenames + dirnames:
            if not ALLOW_HIDDEN and name.startswith("."):
                continue
            if not fnmatch.fnmatch(name, pattern):
                continue

            full = current / name
            relative = _to_relative_display(full)

            excluded = any(fnmatch.fnmatch(relative, ex) for ex in excludes)
            if excluded:
                continue

            matches.append(relative)
            if len(matches) >= max_results:
                return {
                    "path": _to_relative_display(root),
                    "pattern": pattern,
                    "matches": matches,
                    "truncated": True,
                }

    return {
        "path": _to_relative_display(root),
        "pattern": pattern,
        "matches": matches,
        "truncated": False,
    }


@mcp.tool
def search_web(query: str, provider: str = "auto", max_results: int = 5) -> dict[str, Any]:
    """Search the web for real-time information, news, current events, or general knowledge.
    
    Use this tool when you need information that is not available in your local workspace or training data,
    especially for topics that change frequently like weather, news, or recent developments in technology.
    """
    if max_results < 1:
        raise ValueError("max_results must be >= 1")
    max_results = min(max_results, MAX_WEB_SEARCH_RESULTS)

    return search_web_results(
        query=query,
        provider=provider,
        max_results=max_results,
        brave_api_key=os.getenv("BRAVE_SEARCH_API_KEY"),
        tavily_api_key=os.getenv("TAVILY_API_KEY"),
    )


@mcp.tool
def fetch_url(url: str, max_chars: int = MAX_FETCH_CHARS) -> dict[str, Any]:
    """Fetch a webpage and extract readable text content."""
    return fetch_web_content(url=url, max_chars=max_chars)


@mcp.tool
def server_status() -> dict[str, Any]:
    """Operational status and safety config summary for auditing/debugging."""
    return {
        "name": "Atri Code MCP",
        "allowed_directories": [str(p) for p in POLICY.get_allowed_dirs()],
        "max_read_bytes": MAX_READ_BYTES,
        "max_write_bytes": MAX_WRITE_BYTES,
        "max_search_results": MAX_SEARCH_RESULTS,
        "max_web_search_results": MAX_WEB_SEARCH_RESULTS,
        "max_fetch_chars": MAX_FETCH_CHARS,
        "allow_hidden": ALLOW_HIDDEN,
    }


@mcp.tool
def read_media_file_base64(target_file_path: str) -> dict[str, Any]:
    """
    Read binary file and return base64-encoded content.

    This is useful for images/audio similar to common filesystem MCP servers.
    """
    import base64
    import mimetypes

    file_path = _resolve_user_path(target_file_path)
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"File not found: {target_file_path}")

    size = file_path.stat().st_size
    if size > MAX_READ_BYTES:
        raise ValueError(
            f"File too large to read safely ({size} bytes). "
            f"Limit is {MAX_READ_BYTES} bytes."
        )

    raw = file_path.read_bytes()
    mime_type, _ = mimetypes.guess_type(str(file_path))
    return {
        "path": _to_relative_display(file_path),
        "mime_type": mime_type or "application/octet-stream",
        "size": size,
        "base64": base64.b64encode(raw).decode("ascii"),
    }


@mcp.tool
def write_json_file(target_file_path: str, data: dict[str, Any], indent: int = 2) -> dict[str, Any]:
    """Write JSON object to a file using safe atomic write."""
    content = json.dumps(data, ensure_ascii=False, indent=indent) + "\n"
    return write_file(target_file_path=target_file_path, content=content, overwrite=True)


@mcp.tool
def edit_diff(target_file_path: str, diff: str) -> str:
    """
    Apply a unified diff (patch) to a file.
    REQUIRED: 'target_file_path' must be the path to the file you want to edit.
    REQUIRED: 'diff' must be a valid unified diff string starting with '---' and '+++'.
    
    If this fails, the tool will return the current content of the file to help you fix the hunk context.
    """
    try:
        if not target_file_path:
            return "Error: Missing required argument 'target_file_path'"
        
        full_path = _resolve_user_path(target_file_path)
        if not full_path.exists():
            return f"Error: File not found: {target_file_path}"

        success = DiffEngine.apply_diff(str(full_path), diff)
        if success:
            return f"Successfully applied diff to {target_file_path}"
        else:
            # Provide the current content to help the agent self-correct
            content = full_path.read_text(encoding="utf-8")
            return (
                f"Error: Failed to apply diff to {target_file_path}. The hunk context lines or line numbers do not match exactly.\n\n"
                f"CURRENT FILE CONTENT of {target_file_path} (Use this to fix your diff):\n"
                f"```\n{content}\n```"
            )
    except Exception as e:
        return f"Error applying diff: {e}"


@mcp.tool
def edit_file_hashline(path: str, edits: str) -> dict[str, Any]:
    """
    Edit a file using hash-anchored DSL. Atomic: ALL hashes are validated
    before any bytes are written. If any hash mismatches the actual file
    content, the entire operation is rejected with an error — the file is
    left completely unchanged.

    Use read_text_file with hashline=True to get anchor values for a file,
    then construct the edit DSL from those anchors.

    edits DSL format (blocks separated by ---):

      = START#HASH..END#HASH    replace the line range with the following lines
      + ANCHOR#HASH             insert the following lines after the anchor line
      < ANCHOR#HASH             insert the following lines before the anchor line
      - START#HASH..END#HASH    delete the line range (no following content)

    Example:
      = 3#a1b2..5#c3d4
      new line replacing lines 3-5
      ---
      + 7#d4e5
      line inserted after line 7
      ---
      - 10#f6g7..12#h8i9
    """
    if _encode_file is None or _apply_hashline_edits is None:
        return {"ok": False, "error": "hashline module not available in this environment"}

    try:
        full_path = _resolve_user_path(path)
    except (PermissionError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}

    if not full_path.exists() or not full_path.is_file():
        return {"ok": False, "error": f"File not found: {path}"}

    original = _read_text(full_path)

    try:
        updated = _apply_hashline_edits(original, edits)
    except _HashMismatchError as exc:
        return {
            "ok": False,
            "error": f"Hash mismatch — no changes written: {exc}",
        }
    except ValueError as exc:
        return {
            "ok": False,
            "error": f"DSL parse error: {exc}",
        }

    encoded = updated.encode("utf-8")
    if len(encoded) > MAX_WRITE_BYTES:
        return {
            "ok": False,
            "error": f"Resulting file too large ({len(encoded)} bytes, limit {MAX_WRITE_BYTES})",
        }

    temp = full_path.with_suffix(full_path.suffix + ".hl.tmp")
    temp.write_text(updated, encoding="utf-8")
    temp.replace(full_path)

    return {
        "ok": True,
        "path": _to_relative_display(full_path),
        "bytes_written": len(encoded),
    }


@mcp.tool
def create_project(target_project_path: str, template: str = "python-basic") -> str:
    """
    Create a new project structure at the specified path.
    Supported templates: python-basic, node-basic, fastapi-jwt.
    """
    try:
        full_path = _resolve_user_path(target_project_path)
        if full_path.exists():
            return f"Error: Path already exists: {target_project_path}"
        
        os.makedirs(full_path, exist_ok=True)
        
        # Simple scaffolding for now
        if template == "python-basic":
            (full_path / "README.md").write_text(f"# {full_path.name}\n")
            (full_path / "main.py").write_text("def main():\n    print('Hello World')\n\nif __name__ == '__main__':\n    main()\n")
            (full_path / "requirements.txt").write_text("")
        elif template == "fastapi-jwt":
            # Just create the main file for now
            (full_path / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
            
        return f"Successfully created {template} project at {target_project_path}"
    except Exception as e:
        return f"Error creating project: {e}"

# ─── Persistent todo list ─────────────────────────────────────────────────────
# Stored in a JSON file so todos survive MCP server restarts.
_TODO_LOCK = threading.Lock()

def _todo_file() -> Path:
    """Return the path to the persistent todo store."""
    state_dir = Path(__file__).resolve().parents[2] / "runtime" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "todos.json"

def _load_todos() -> list[dict]:
    f = _todo_file()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def _save_todos(todos: list[dict]) -> None:
    _todo_file().write_text(json.dumps(todos, ensure_ascii=False, indent=2), encoding="utf-8")


@mcp.tool
def todo_write(todos: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Replace the current todo list with a new set of tasks.

    Each task dict must have at minimum a 'content' key (str).
    Optional keys: 'status' ('pending'|'in_progress'|'completed'), 'priority' ('high'|'medium'|'low').

    Use this to track multi-step work plans so the user can see progress.
    """
    validated: list[dict[str, Any]] = []
    for item in todos:
        if "content" not in item or not str(item["content"]).strip():
            raise ValueError("Each todo item must have a non-empty 'content' key")
        validated.append({
            "id": len(validated) + 1,
            "content": str(item["content"]).strip(),
            "status": item.get("status", "pending"),
            "priority": item.get("priority", "medium"),
        })
    with _TODO_LOCK:
        _save_todos(validated)
    return {"ok": True, "count": len(validated), "todos": validated}


@mcp.tool
def todo_read() -> dict[str, Any]:
    """Return the current todo list."""
    with _TODO_LOCK:
        todos = _load_todos()
    return {"todos": todos, "count": len(todos)}


# ─── Bash execution ───────────────────────────────────────────────────────────

# Commands that are unconditionally blocked regardless of permission_mode.
_BLOCKED_COMMAND_PATTERNS = [
    "rm -rf /",
    "rm -rf ~",
    "> /dev/sda",
    "dd if=",
    "mkfs",
    ":(){ :|:& };:",  # fork bomb
]

_MAX_OUTPUT_CHARS = 50_000
_MAX_OUTPUT_LINES = 10_000


def _run_subprocess_fallback(cmd: str, timeout: int = 30, env=None, cwd=None) -> dict:
    """Fallback for systems without PTY support (e.g. Windows)."""
    import subprocess
    import time

    t0 = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=cwd,
        )
        elapsed = time.monotonic() - t0
        output = result.stdout + (("\n" + result.stderr) if result.stderr else "")
        lines = output.splitlines()
        truncated = len(lines) > _MAX_OUTPUT_LINES
        if truncated:
            omitted = len(lines) - _MAX_OUTPUT_LINES
            lines = lines[:_MAX_OUTPUT_LINES]
            lines.append(f"[... {omitted} lines truncated ...]")
        return {
            "stdout": "\n".join(lines),
            "exit_code": result.returncode,
            "signal": None,
            "pid": None,
            "truncated": truncated,
            "elapsed_seconds": round(elapsed, 2),
        }
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - t0
        return {
            "stdout": "",
            "exit_code": None,
            "signal": None,
            "pid": None,
            "truncated": False,
            "error": f"timeout after {timeout}s",
            "elapsed_seconds": round(elapsed, 2),
        }


def _run_with_pty(cmd: str, timeout: int = 30, env=None, cwd=None) -> dict:
    """Run cmd in a PTY. Returns dict with stdout, exit_code, pid, signal, elapsed_seconds."""
    import subprocess
    import time

    try:
        master_fd, slave_fd = pty.openpty()
    except (OSError, AttributeError):
        # PTY not available (Windows or restricted environment)
        return _run_subprocess_fallback(cmd, timeout, env, cwd)

    output_chunks: list[bytes] = []
    line_count = 0
    truncated = False
    t0 = time.monotonic()

    try:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            env=env,
            cwd=cwd,
        )
        os.close(slave_fd)  # close slave in parent after forking

        deadline = t0 + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                proc.kill()
                break
            try:
                rlist, _, _ = select.select([master_fd], [], [], min(remaining, 0.1))
            except (ValueError, OSError):
                break
            if rlist:
                try:
                    chunk = os.read(master_fd, 4096)
                    if not chunk:
                        break
                    new_lines = chunk.count(b"\n")
                    if not truncated:
                        output_chunks.append(chunk)
                        line_count += new_lines
                        if line_count > _MAX_OUTPUT_LINES:
                            truncated = True
                except OSError:
                    break

            if proc.poll() is not None:
                # Drain any remaining output
                try:
                    while True:
                        rlist2, _, _ = select.select([master_fd], [], [], 0.05)
                        if not rlist2:
                            break
                        chunk = os.read(master_fd, 4096)
                        if not chunk:
                            break
                        if not truncated:
                            output_chunks.append(chunk)
                            line_count += chunk.count(b"\n")
                            if line_count > _MAX_OUTPUT_LINES:
                                truncated = True
                except OSError:
                    pass
                break

        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

        elapsed = time.monotonic() - t0
        exit_code = proc.returncode
        signal_num = None
        if exit_code is not None and exit_code < 0:
            signal_num = -exit_code
            exit_code = None

    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass

    raw = b"".join(output_chunks)

    # Binary detection: if output is not valid UTF-8, report as binary
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return {
            "type": "binary_output",
            "size_bytes": len(raw),
            "pid": proc.pid,
            "exit_code": exit_code,
            "signal": signal_num,
            "message": f"binary output, {len(raw)} bytes",
            "elapsed_seconds": round(elapsed, 2),
        }

    lines = text.splitlines()
    if len(lines) > _MAX_OUTPUT_LINES:
        omitted = len(lines) - _MAX_OUTPUT_LINES
        lines = lines[:_MAX_OUTPUT_LINES]
        lines.append(f"[... {omitted} lines truncated ...]")
        truncated = True

    return {
        "stdout": "\n".join(lines),
        "exit_code": exit_code,
        "signal": signal_num,
        "pid": proc.pid,
        "truncated": truncated,
        "elapsed_seconds": round(elapsed, 2),
    }


@mcp.tool
def bash_exec(
    command: str,
    cwd: str | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    """
    Execute a shell command and return its output.

    - Output is capped at 10 000 lines (PTY scrollback limit); excess lines are
      replaced with a truncation notice.
    - Timeout default is 30 s; max is 120 s.
    - A small set of obviously destructive commands is unconditionally blocked.
    - The working directory defaults to the first allowed directory (or repo root).
    - Uses a PTY on Linux/macOS for realistic terminal output; falls back to
      subprocess.PIPE on systems where PTY is unavailable.

    Use for: running tests, git commands, build scripts, inspecting processes.
    Do NOT use for: interactive programs, long-running daemons (use & to background).
    """
    import time

    # Safety: block obviously destructive patterns
    for pattern in _BLOCKED_COMMAND_PATTERNS:
        if pattern in command:
            return {"ok": False, "error": f"Blocked: command matches disallowed pattern '{pattern}'"}

    # Resolve working directory
    work_dir: Path
    if cwd:
        work_dir = _resolve_user_path(cwd)
    else:
        allowed = _load_allowed_dirs()
        work_dir = allowed[0] if allowed else Path.cwd()

    timeout = min(int(timeout_seconds), 120)

    t0 = time.monotonic()
    try:
        result = _run_with_pty(
            cmd=command,
            timeout=timeout,
            env={**os.environ},
            cwd=str(work_dir),
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    if "error" in result:
        return {"ok": False, "error": result["error"]}

    # Binary output path
    if result.get("type") == "binary_output":
        return {
            "ok": False,
            "error": result["message"],
            "pid": result.get("pid"),
            "exit_code": result.get("exit_code"),
            "signal": result.get("signal"),
            "elapsed_seconds": result.get("elapsed_seconds"),
        }

    exit_code = result.get("exit_code")
    stdout = result.get("stdout", "")
    elapsed = result.get("elapsed_seconds", round(time.monotonic() - t0, 2))
    total_bytes = len(stdout.encode("utf-8", errors="replace"))
    header = f"[exit:{exit_code} | elapsed:{elapsed:.1f}s | pid:{result.get('pid')} | {total_bytes} bytes]\n"

    return {
        "ok": exit_code == 0,
        "exit_code": exit_code,
        "signal": result.get("signal"),
        "pid": result.get("pid"),
        "output": header + stdout,
        "truncated": result.get("truncated", False),
        "elapsed_seconds": elapsed,
    }


# ─── Grep / codebase search ───────────────────────────────────────────────────

@mcp.tool
def grep_codebase(
    pattern: str,
    path: str = ".",
    file_glob: str = "*",
    case_sensitive: bool = True,
    max_results: int = 200,
) -> dict[str, Any]:
    """
    Search for a regex pattern across files in the codebase.

    Uses ripgrep (rg) when available, falls back to Python's re module.

    Args:
        pattern: Regular expression to search for.
        path: Directory or file to search in (defaults to allowed root).
        file_glob: Glob pattern to filter files, e.g. '*.py', '*.ts'.
        case_sensitive: Whether the search is case-sensitive.
        max_results: Maximum number of matches to return (cap 500).

    Returns a list of matches with file path, line number, and line content.
    """
    import re
    import subprocess

    search_root = _resolve_user_path(path)
    max_results = min(int(max_results), 500)

    # Try ripgrep first
    rg = shutil.which("rg")
    if rg:
        flags = [] if case_sensitive else ["-i"]
        cmd = [rg, "--json", "-m", str(max_results), "--glob", file_glob] + flags + [pattern, str(search_root)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            matches: list[dict[str, Any]] = []
            for line in proc.stdout.splitlines():
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "match":
                        data = obj["data"]
                        matches.append({
                            "file": _to_relative_display(Path(data["path"]["text"])),
                            "line": data["line_number"],
                            "content": data["lines"]["text"].rstrip("\n"),
                        })
                except (json.JSONDecodeError, KeyError):
                    continue
            return {"ok": True, "matches": matches, "count": len(matches), "engine": "ripgrep"}
        except Exception:
            pass  # Fall through to Python fallback

    # Python fallback — excluded directories to prevent scanning large non-code dirs
    _SKIP_DIRS = frozenset({
        "node_modules", ".git", "__pycache__", ".venv", "venv", "env",
        ".next", "build", "dist", ".pytest_cache", "models", ".mypy_cache",
    })
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        regex = re.compile(pattern, flags)
    except re.error as exc:
        return {"ok": False, "error": f"Invalid regex: {exc}", "matches": []}

    matches: list[dict[str, Any]] = []
    glob_re = re.compile(fnmatch.translate(file_glob))

    for dirpath, dirnames, filenames in os.walk(str(search_root)):
        # Prune excluded dirs in-place so os.walk doesn't descend into them
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            if not glob_re.match(fname):
                continue
            fpath = Path(dirpath) / fname
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    matches.append({
                        "file": _to_relative_display(fpath),
                        "line": lineno,
                        "content": line.rstrip("\n"),
                    })
                    if len(matches) >= max_results:
                        return {"ok": True, "matches": matches, "count": len(matches), "engine": "python", "truncated": True}

    return {"ok": True, "matches": matches, "count": len(matches), "engine": "python"}


# ─── Code intelligence ────────────────────────────────────────────────────────

_SYMBOL_SKIP_DIRS = frozenset({
    "node_modules", ".git", "__pycache__", ".venv", "venv", "env",
    ".next", "build", "dist", ".pytest_cache", "models", ".mypy_cache",
})

# Tree-sitter availability — try import at module load; degrade gracefully
try:
    import tree_sitter  # noqa: F401
    from tree_sitter import Language, Parser
    _TS_AVAILABLE = True
except ImportError:
    _TS_AVAILABLE = False

# Lazy cache of loaded tree-sitter Language objects
_TS_LANGUAGES: dict[str, Any] = {}


def _load_ts_language(lang: str) -> Any:
    """Lazy-load a tree-sitter language grammar. Returns None if unavailable."""
    if lang in _TS_LANGUAGES:
        return _TS_LANGUAGES[lang]
    try:
        if lang == "python":
            import tree_sitter_python as tsp
            _TS_LANGUAGES[lang] = Language(tsp.language())
        elif lang == "typescript":
            import tree_sitter_typescript as tsts
            _TS_LANGUAGES[lang] = Language(tsts.language_typescript())
        elif lang == "javascript":
            import tree_sitter_javascript as tsjs
            _TS_LANGUAGES[lang] = Language(tsjs.language())
        elif lang == "go":
            import tree_sitter_go as tsgo
            _TS_LANGUAGES[lang] = Language(tsgo.language())
        elif lang == "rust":
            import tree_sitter_rust as tsrust
            _TS_LANGUAGES[lang] = Language(tsrust.language())
    except (ImportError, Exception):
        pass
    return _TS_LANGUAGES.get(lang)


@mcp.tool()
def search_symbols(
    query: Optional[str] = None,
    path: str = ".",
    language: str = "auto",
    kinds: list[str] | None = None,
    # Aliases: small models reach for 'symbol'/'name' instead of 'query'.
    symbol: Optional[str] = None,
    name: Optional[str] = None,
) -> dict[str, Any]:
    """
    Search for code symbols (functions, classes, methods) by name pattern.
    Supports glob patterns (e.g. 'get_*', '*Handler'). Uses tree-sitter when
    available, falls back to regex grep.

    Args:
        query: Symbol name pattern (supports * and ? glob wildcards). Aliases: symbol, name.
        path: Directory or file to search (default: current directory)
        language: Language hint ('python','typescript','javascript','go','rust','auto')
        kinds: Symbol types to find ('function','class','method','variable'). Default: all
    """
    import fnmatch
    import re

    query = query or symbol or name
    if not query:
        raise ValueError(
            "Missing required argument 'query' (the symbol name pattern). "
            "Accepted aliases: symbol, name."
        )

    if kinds is None:
        kinds = ["function", "class", "method", "variable"]

    root = _resolve_user_path(path)
    results: list[dict] = []

    # Extension → language map
    EXT_LANG = {
        ".py": "python", ".pyi": "python",
        ".ts": "typescript", ".tsx": "typescript",
        ".js": "javascript", ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
    }

    # Regex fallbacks per language
    REGEX_PATTERNS: dict[str, dict[str, str]] = {
        "python": {
            "function": r"^def\s+(\w+)",
            "class": r"^class\s+(\w+)",
            "method": r"^\s+def\s+(\w+)",
        },
        "typescript": {
            "function": r"(?:function\s+(\w+)|const\s+(\w+)\s*=\s*(?:async\s*)?\()",
            "class": r"class\s+(\w+)",
        },
        "javascript": {
            "function": r"(?:function\s+(\w+)|const\s+(\w+)\s*=\s*(?:async\s*)?\()",
            "class": r"class\s+(\w+)",
        },
        "go": {
            "function": r"^func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)",
        },
        "rust": {
            "function": r"^(?:pub\s+)?fn\s+(\w+)",
            "struct": r"^(?:pub\s+)?struct\s+(\w+)",
        },
    }

    files_to_search: list[Path] = []
    if root.is_file():
        files_to_search = [root]
    else:
        for ext in EXT_LANG:
            files_to_search.extend(root.rglob(f"*{ext}"))
        files_to_search = [
            f for f in files_to_search
            if not any(part in (".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build")
                       for part in f.parts)
        ]

    # glob pattern: if query contains no wildcards, treat as substring match
    glob_query = query if ("*" in query or "?" in query) else f"*{query}*"

    for fpath in files_to_search:
        if len(results) >= 200:
            break
        lang = language if language != "auto" else EXT_LANG.get(fpath.suffix, "")
        if not lang:
            continue

        try:
            src = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        found_via_ts = False
        if _TS_AVAILABLE:
            ts_lang = _load_ts_language(lang)
            if ts_lang:
                try:
                    parser = Parser(ts_lang)
                    tree = parser.parse(src.encode("utf-8"))

                    TS_KIND_TYPES: dict[str, dict[str, list[str]]] = {
                        "python": {
                            "function": ["function_definition"],
                            "class": ["class_definition"],
                            "method": ["function_definition"],
                        },
                        "typescript": {
                            "function": ["function_declaration", "arrow_function", "method_definition"],
                            "class": ["class_declaration"],
                        },
                        "javascript": {
                            "function": ["function_declaration", "arrow_function"],
                            "class": ["class_declaration"],
                        },
                        "go": {"function": ["function_declaration", "method_declaration"]},
                        "rust": {"function": ["function_item"], "struct": ["struct_item"]},
                    }
                    lang_types = TS_KIND_TYPES.get(lang, {})

                    def _walk(node: Any) -> None:
                        for kind, ts_types in lang_types.items():
                            if kind not in kinds:
                                continue
                            if node.type in ts_types:
                                for child in node.children:
                                    if child.type in ("identifier", "name", "property_identifier"):
                                        name = child.text.decode("utf-8") if child.text else ""
                                        if name and fnmatch.fnmatch(name, glob_query):
                                            results.append({
                                                "name": name,
                                                "kind": kind,
                                                "file": str(_to_relative_display(fpath)),
                                                "line": node.start_point[0] + 1,
                                            })
                                        break
                        for child in node.children:
                            if len(results) < 200:
                                _walk(child)

                    _walk(tree.root_node)
                    found_via_ts = True
                except Exception:
                    pass

        if not found_via_ts:
            lang_patterns = REGEX_PATTERNS.get(lang, {})
            lines = src.splitlines()
            for i, line_text in enumerate(lines, 1):
                for kind, pat in lang_patterns.items():
                    if kind not in kinds:
                        continue
                    m = re.search(pat, line_text)
                    if m:
                        name = next((g for g in m.groups() if g), None)
                        if name and fnmatch.fnmatch(name, glob_query):
                            results.append({
                                "name": name,
                                "kind": kind,
                                "file": str(_to_relative_display(fpath)),
                                "line": i,
                            })
                if len(results) >= 200:
                    break

    return {
        "ok": True,
        "query": query,
        "results": results,
        "total": len(results),
        "engine": "tree-sitter" if _TS_AVAILABLE else "regex",
        "truncated": len(results) >= 200,
    }


@mcp.tool
def get_repo_map(max_depth: int = 3) -> str:
    """
    Get a high-level overview of the project structure.

    Returns a text summary including: top-level directories, file counts by
    language, and the first docstring/comment line of key entry-point files
    (main.py, app.py, index.ts, etc.).

    Args:
        max_depth: How many directory levels to traverse (1–6).
    """
    max_depth = max(1, min(int(max_depth), 6))
    root = POLICY.get_allowed_dirs()[0]

    _SKIP = frozenset({
        "node_modules", ".git", "__pycache__", ".venv", "venv", "env",
        ".next", "build", "dist", ".pytest_cache", "models", ".mypy_cache",
        ".ruff_cache", ".mypy_cache", "target", "out",
    })
    _ENTRY_NAMES = frozenset({
        "main.py", "app.py", "server.py", "api.py", "index.py",
        "index.ts", "index.js", "app.ts", "app.js", "main.ts", "main.js",
        "manage.py", "__init__.py", "cli.py",
    })
    _EXT_LANG: dict[str, str] = {
        ".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript",
        ".js": "JavaScript", ".jsx": "JavaScript", ".rs": "Rust",
        ".go": "Go", ".sh": "Shell", ".md": "Markdown",
        ".json": "JSON", ".yaml": "YAML", ".yml": "YAML",
        ".toml": "TOML", ".html": "HTML", ".css": "CSS",
    }

    ext_counts: dict[str, int] = {}
    entry_points: list[dict[str, str]] = []
    dir_lines: list[str] = []

    def _walk(path: Path, depth: int, prefix: str) -> None:
        if depth <= 0:
            return
        try:
            items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except PermissionError:
            return
        for item in items:
            if item.name.startswith(".") or item.name in _SKIP:
                continue
            rel = _to_relative_display(item)
            if item.is_dir():
                dir_lines.append(f"{prefix}{item.name}/")
                _walk(item, depth - 1, prefix + "  ")
            else:
                ext = item.suffix.lower()
                lang = _EXT_LANG.get(ext, "other")
                ext_counts[lang] = ext_counts.get(lang, 0) + 1
                if item.name in _ENTRY_NAMES:
                    # Grab first non-empty line (docstring/comment hint)
                    hint = ""
                    try:
                        first_lines = item.read_text(encoding="utf-8", errors="replace").splitlines()
                        for ln in first_lines[:10]:
                            stripped = ln.strip().strip('"""').strip("'''").strip("#").strip()
                            if stripped and not stripped.startswith("from ") and not stripped.startswith("import "):
                                hint = stripped[:80]
                                break
                    except OSError:
                        pass
                    entry_points.append({"path": rel, "hint": hint})

    _walk(root, max_depth, "")

    lines = [f"# Project: {root.name}", ""]
    if dir_lines:
        lines.append("## Structure")
        lines.extend(dir_lines[:80])
        if len(dir_lines) > 80:
            lines.append(f"  ... ({len(dir_lines) - 80} more entries)")
        lines.append("")

    if ext_counts:
        lines.append("## File Counts by Language")
        for lang, count in sorted(ext_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {lang}: {count}")
        lines.append("")

    if entry_points:
        lines.append("## Entry Points")
        for ep in entry_points[:20]:
            hint_str = f"  — {ep['hint']}" if ep["hint"] else ""
            lines.append(f"  {ep['path']}{hint_str}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool
def propose_plan(goal: str, steps: list[str]) -> dict[str, Any]:
    """
    Propose a multi-step plan for a complex task.

    Call this before starting a large task so the user can review the approach.
    The plan is saved to the todo list so it persists across turns.

    Args:
        goal: High-level description of what you're trying to accomplish.
        steps: Ordered list of concrete actions you plan to take.

    Returns the saved plan. The orchestrator will display it to the user.
    """
    if not goal or not goal.strip():
        return {"ok": False, "error": "goal must be non-empty"}
    if not steps or not isinstance(steps, list):
        return {"ok": False, "error": "steps must be a non-empty list"}

    todos = [
        {"content": f"[Goal] {goal.strip()}", "status": "in_progress", "priority": "high"},
    ]
    for i, step in enumerate(steps, 1):
        todos.append({
            "content": f"Step {i}: {str(step).strip()}",
            "status": "pending",
            "priority": "medium",
        })

    # Persist to todo store so the user sees it
    todo_write(todos=todos)

    return {
        "ok": True,
        "goal": goal.strip(),
        "steps": [str(s).strip() for s in steps],
        "step_count": len(steps),
        "message": "Plan saved to todo list. Proceed step by step and mark each complete with todo_write.",
    }


# ─── Git diff (read-only) ─────────────────────────────────────────────────────

@mcp.tool
def view_git_diff(
    path: str = ".",
    staged: bool = False,
    base: str = "HEAD",
) -> dict[str, Any]:
    """
    Show git diff for a file or directory (read-only, no side effects).

    Args:
        path: File or directory to diff, relative to project root. Defaults to '.'.
        staged: If True, show staged changes (git diff --cached). Defaults to False.
        base: Base ref to diff against, e.g. 'HEAD', 'main', 'HEAD~1'. Defaults to 'HEAD'.

    Returns the unified diff text, or a message if there are no changes.
    """
    import subprocess

    try:
        target = _resolve_user_path(path)
    except (PermissionError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "diff": ""}

    cmd = ["git", "diff", base]
    if staged:
        cmd = ["git", "diff", "--cached", base]
    cmd.append(str(target))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(POLICY.get_allowed_dirs()[0]),
        )
        diff_text = result.stdout
        if not diff_text.strip():
            diff_text = "(No changes)" if not staged else "(No staged changes)"
        return {
            "ok": True,
            "path": _to_relative_display(target),
            "staged": staged,
            "base": base,
            "diff": diff_text,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "git diff timed out after 15s", "diff": ""}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "diff": ""}


# ─── File watch / monitor tools ───────────────────────────────────────────────

@mcp.tool()
def watch_file(watch_id: str, path: str, pattern: str = "") -> dict[str, Any]:
    """
    Start watching a file or directory for changes. Changes are logged to the event history.

    Args:
        watch_id: Unique identifier for this watcher (used to stop it later)
        path: File or directory path to watch
        pattern: Optional glob pattern to filter files (e.g. '*.py'). Only for directories.
    """
    try:
        from .monitor import start_watch, _WATCHDOG_AVAILABLE
    except ImportError:
        try:
            from monitor import start_watch, _WATCHDOG_AVAILABLE
        except ImportError:
            return {"ok": False, "error": "monitor module not available"}

    resolved = _resolve_user_path(path)

    def _on_change(event: dict) -> None:
        LOGGER.info("File watch event: %s %s", event.get("type"), event.get("path"))

    start_watch(watch_id, str(resolved), _on_change, pattern or None)
    return {
        "ok": True,
        "watch_id": watch_id,
        "path": str(resolved),
        "backend": "watchdog" if _WATCHDOG_AVAILABLE else "polling",
    }


@mcp.tool()
def stop_watch_file(watch_id: str) -> dict[str, Any]:
    """Stop a file watcher started with watch_file."""
    try:
        from .monitor import stop_watch, list_watches
    except ImportError:
        try:
            from monitor import stop_watch, list_watches
        except ImportError:
            return {"ok": False, "error": "monitor module not available"}

    stopped = stop_watch(watch_id)
    return {"ok": stopped, "watch_id": watch_id, "remaining_watches": list_watches()}


@mcp.tool()
def invoke_skill(name: str) -> dict[str, Any]:
    """
    Invoke a named skill to load its full instructions.
    Skills are defined in SKILL.md files under ~/.atri/skills/ or .atri/skills/.
    """
    try:
        from .skills_loader import discover_skills, get_skill_body
    except ImportError:
        try:
            from skills_loader import discover_skills, get_skill_body
        except ImportError:
            # Path-based import: orchestrator and mcp are sibling directories
            import importlib.util as _ilu
            _sl_path = Path(__file__).parent.parent / "orchestrator" / "skills_loader.py"
            if _sl_path.exists():
                _spec = _ilu.spec_from_file_location("skills_loader", str(_sl_path))
                if _spec and _spec.loader:
                    _mod = _ilu.module_from_spec(_spec)
                    _spec.loader.exec_module(_mod)
                    discover_skills = _mod.discover_skills
                    get_skill_body = _mod.get_skill_body
                else:
                    return {"ok": False, "error": "skills_loader not available"}
            else:
                return {"ok": False, "error": "skills_loader not available"}

    skills = discover_skills()
    body = get_skill_body(name, skills)
    if body is None:
        available = list(skills.keys())
        return {"ok": False, "error": f"Skill '{name}' not found", "available_skills": available}

    return {"ok": True, "name": name, "instructions": body}


@mcp.tool()
def read_tool_result(turn_id: str) -> dict[str, Any]:
    """
    Read the full content of a distilled tool result that was truncated.
    The turn_id is shown in the truncation notice (e.g. '3_read_text_file').
    """
    results_dir = Path.home() / ".atri" / "tool_results"
    result_file = results_dir / f"{turn_id}.txt"
    if not result_file.exists():
        return {"ok": False, "error": f"No result found for turn_id: {turn_id}"}
    try:
        content = result_file.read_text(encoding="utf-8")
        return {"ok": True, "turn_id": turn_id, "content": content, "size": len(content)}
    except OSError as e:
        return {"ok": False, "error": str(e)}


# ── E.4: Persistent retain/recall memory tools ────────────────────────────────
_MEMORY_DIR = Path.home() / ".atri" / "memory"


@mcp.tool()
def retain(key: str, value: str) -> str:
    """Store a persistent key-value memory that survives session compaction and restarts."""
    _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    safe_key = re.sub(r"[^\w\-]", "_", key)[:64]
    (_MEMORY_DIR / f"{safe_key}.json").write_text(
        json.dumps({"key": key, "value": value, "timestamp": time.time()})
    )
    return f"Retained: {key}"


@mcp.tool()
def recall(key: str) -> str:
    """Retrieve a previously retained memory by key. Returns the stored value or a not-found message."""
    safe_key = re.sub(r"[^\w\-]", "_", key)[:64]
    path = _MEMORY_DIR / f"{safe_key}.json"
    if not path.exists():
        return f"No memory found for key: {key}"
    try:
        return json.loads(path.read_text())["value"]
    except Exception:
        return f"Error reading memory for key: {key}"


@mcp.tool()
def list_memories() -> str:
    """List all retained memory keys."""
    if not _MEMORY_DIR.exists():
        return "No memories stored."
    keys = []
    for p in sorted(_MEMORY_DIR.glob("*.json")):
        try:
            keys.append(json.loads(p.read_text()).get("key", p.stem))
        except Exception:
            keys.append(p.stem)
    return "\n".join(keys) if keys else "No memories stored."
# ──────────────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    _initialize_server()
    mcp.run()
