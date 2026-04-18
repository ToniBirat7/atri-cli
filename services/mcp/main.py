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
import json
import logging
import os
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .search_adapter import fetch_web_content, search_web_results
except ImportError:
    from search_adapter import fetch_web_content, search_web_results

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


LOGGER = logging.getLogger("tarbar.mcp.filesystem")
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


INITIAL_ALLOWED_DIRS = _load_allowed_dirs()
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


POLICY = _RuntimePolicy(INITIAL_ALLOWED_DIRS)

mcp = FastMCP("Tarbar Filesystem MCP")


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

    if not ALLOW_HIDDEN and _has_hidden_component(resolved):
        raise PermissionError(
            f"Access denied for hidden path '{user_path}'. "
            "Set MCP_ALLOW_HIDDEN=true to allow hidden files/directories."
        )

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
def set_allowed_directory(path: str) -> dict[str, Any]:
    """
    Set a single active allowed directory at runtime.

    Intended for user-selected workspace roots from frontend/orchestrator.
    """
    validated = _validate_directories([path])
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
def list_directory(path: str = ".") -> dict[str, Any]:
    """List immediate directory contents."""
    directory = _resolve_user_path(path)
    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {path}")
    if not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {path}")

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
def directory_tree(path: str = ".", max_depth: int = 4) -> dict[str, Any]:
    """Return a recursive JSON tree of directories/files."""
    if max_depth < 1 or max_depth > 12:
        raise ValueError("max_depth must be between 1 and 12")
    root = _resolve_user_path(path)
    if not root.exists():
        raise FileNotFoundError(f"Path not found: {path}")
    return _build_tree(root, max_depth)


@mcp.tool
def read_text_file(path: str, head: int | None = None, tail: int | None = None) -> dict[str, Any]:
    """
    Read UTF-8 text content from a file.

    Optional slicing:
    - head: first N lines
    - tail: last N lines
    """
    if head is not None and tail is not None:
        raise ValueError("Specify only one of head or tail")

    file_path = _resolve_user_path(path)
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

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
    return {
        "path": _to_relative_display(file_path),
        "content": final,
        "line_count": len(lines),
    }


@mcp.tool
def read_multiple_files(paths: list[str]) -> dict[str, Any]:
    """Read multiple text files; failures are captured per file."""
    results: list[dict[str, Any]] = []
    for p in paths:
        try:
            result = read_text_file(p)
            results.append({"path": p, "ok": True, "result": result})
        except Exception as exc:
            results.append({"path": p, "ok": False, "error": str(exc)})
    return {"results": results}


@mcp.tool
def get_file_info(path: str) -> dict[str, Any]:
    """Get metadata for a file or directory."""
    target = _resolve_user_path(path)
    if not target.exists():
        raise FileNotFoundError(f"Path not found: {path}")

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
def create_directory(path: str) -> dict[str, Any]:
    """Create directory recursively; succeeds if it already exists."""
    target = _resolve_user_path(path)
    target.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "path": _to_relative_display(target)}


@mcp.tool
def write_file(path: str, content: str, overwrite: bool = True) -> dict[str, Any]:
    """
    Write text to file (UTF-8).

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

    target = _resolve_user_path(path)
    if target.exists() and not overwrite:
        raise FileExistsError(f"File already exists and overwrite=false: {path}")

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
def append_file(path: str, content: str) -> dict[str, Any]:
    """Append UTF-8 text to an existing or new file."""
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_WRITE_BYTES:
        raise ValueError(
            f"Content too large to append safely ({len(encoded)} bytes). "
            f"Limit is {MAX_WRITE_BYTES} bytes."
        )

    target = _resolve_user_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fp:
        fp.write(content)

    return {
        "ok": True,
        "path": _to_relative_display(target),
        "bytes_appended": len(encoded),
    }


@mcp.tool
def edit_file(path: str, old_text: str, new_text: str, dry_run: bool = False) -> dict[str, Any]:
    """
    Replace text in a file.

    This is intentionally simple and deterministic:
    - exact text replacement, all occurrences
    - dry_run previews count and size delta
    """
    if old_text == "":
        raise ValueError("old_text cannot be empty")

    target = _resolve_user_path(path)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    original = _read_text(target)
    count = original.count(old_text)
    if count == 0:
        raise ValueError("old_text not found in file")

    updated = original.replace(old_text, new_text)
    delta = len(updated.encode("utf-8")) - len(original.encode("utf-8"))

    if dry_run:
        return {
            "ok": True,
            "path": _to_relative_display(target),
            "matches": count,
            "byte_delta": delta,
            "applied": False,
        }

    write_file(path=path, content=updated, overwrite=True)
    return {
        "ok": True,
        "path": _to_relative_display(target),
        "matches": count,
        "byte_delta": delta,
        "applied": True,
    }


@mcp.tool
def move_file(source: str, destination: str, overwrite: bool = False) -> dict[str, Any]:
    """Move or rename file/directory within allowed directories."""
    src = _resolve_user_path(source)
    dst = _resolve_user_path(destination)

    if not src.exists():
        raise FileNotFoundError(f"Source not found: {source}")
    if dst.exists() and not overwrite:
        raise FileExistsError(f"Destination exists and overwrite=false: {destination}")

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
def delete_path(path: str, recursive: bool = False) -> dict[str, Any]:
    """
    Delete a file or directory.

    Safety:
    - directories require recursive=true
    """
    target = _resolve_user_path(path)
    if not target.exists():
        raise FileNotFoundError(f"Path not found: {path}")

    if target.is_dir():
        if not recursive:
            raise ValueError("Refusing to delete directory without recursive=true")
        shutil.rmtree(target)
    else:
        target.unlink()

    return {"ok": True, "deleted": _to_relative_display(target)}


@mcp.tool
def search_files(
    path: str,
    pattern: str,
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

    root = _resolve_user_path(path)
    if not root.exists() or not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {path}")

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
    """Search the web with a provider-neutral adapter."""
    if max_results < 1:
        raise ValueError("max_results must be >= 1")
    max_results = min(max_results, MAX_WEB_SEARCH_RESULTS)

    return search_web_results(
        query=query,
        provider=provider,
        max_results=max_results,
        brave_api_key=os.getenv("BRAVE_SEARCH_API_KEY"),
    )


@mcp.tool
def fetch_url(url: str, max_chars: int = MAX_FETCH_CHARS) -> dict[str, Any]:
    """Fetch a webpage and extract readable text content."""
    return fetch_web_content(url=url, max_chars=max_chars)


@mcp.tool
def server_status() -> dict[str, Any]:
    """Operational status and safety config summary for auditing/debugging."""
    return {
        "name": "Tarbar Filesystem MCP",
        "allowed_directories": [str(p) for p in POLICY.get_allowed_dirs()],
        "max_read_bytes": MAX_READ_BYTES,
        "max_write_bytes": MAX_WRITE_BYTES,
        "max_search_results": MAX_SEARCH_RESULTS,
        "max_web_search_results": MAX_WEB_SEARCH_RESULTS,
        "max_fetch_chars": MAX_FETCH_CHARS,
        "allow_hidden": ALLOW_HIDDEN,
    }


@mcp.tool
def read_media_file_base64(path: str) -> dict[str, Any]:
    """
    Read binary file and return base64-encoded content.

    This is useful for images/audio similar to common filesystem MCP servers.
    """
    import base64
    import mimetypes

    file_path = _resolve_user_path(path)
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

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
def write_json_file(path: str, data: dict[str, Any], indent: int = 2) -> dict[str, Any]:
    """Write JSON object to a file using safe atomic write."""
    content = json.dumps(data, ensure_ascii=False, indent=indent) + "\n"
    return write_file(path=path, content=content, overwrite=True)


if __name__ == "__main__":
    mcp.run()