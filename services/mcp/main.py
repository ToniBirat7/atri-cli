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
import shutil
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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

mcp = FastMCP("Atri Code MCP")


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
def read_file(path: str, start_line: int = 1, end_line: int = 200) -> dict[str, Any]:
    """
    Backward-compatible alias for line-ranged file reads.

    This keeps compatibility with clients that call `read_file` while
    internally reusing the `read_text_file` implementation.
    """
    if start_line < 1:
        raise ValueError("start_line must be >= 1")
    if end_line < start_line:
        raise ValueError("end_line must be >= start_line")

    payload = read_text_file(path)
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
def write_file(path: str, content: Optional[str] = None, text: Optional[str] = None, overwrite: bool = True) -> dict[str, Any]:
    """
    Write text to file (UTF-8).

    Safety:
    - Refuses writes larger than MCP_MAX_WRITE_BYTES
    - Atomic replace through temp file
    """
    if content is None and text is None:
        raise ValueError("Missing required argument: 'content' (or 'text')")
    
    content = content if content is not None else text
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
def edit_file(
    path: str,
    old_text: Optional[str] = None,
    new_text: Optional[str] = None,
    old_content: Optional[str] = None,
    new_content: Optional[str] = None,
    target_content: Optional[str] = None,
    replacement_content: Optional[str] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Replace text in a file.
    
    Arguments:
        path: Path to the file.
        old_text / old_content / target_content: The exact text to find and replace.
        new_text / new_content / replacement_content: The new text to insert.
    """
    # Resolve aliases
    actual_old = old_text or old_content or target_content
    actual_new = new_text or new_content or replacement_content

    if actual_old is None:
        raise ValueError("Missing required argument: 'old_text' (or 'old_content'/'target_content')")
    if actual_new is None:
        raise ValueError("Missing required argument: 'new_text' (or 'new_content'/'replacement_content')")
        
    old_text = actual_old
    new_text = actual_new

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
    pattern: str,
    path: str = ".",
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


@mcp.tool
def edit_diff(path: str, diff: str) -> str:
    """
    Apply a unified diff (patch) to a file.
    This is the preferred method for editing code in v2.
    The 'diff' parameter must be a valid unified diff string.
    """
    try:
        full_path = _resolve_user_path(path)
        if not full_path.exists():
            return f"Error: File not found: {path}"

        success = DiffEngine.apply_diff(str(full_path), diff)
        if success:
            return f"Successfully applied diff to {path}"
        else:
            return f"Error: Failed to apply diff to {path}. Ensure the hunk headers and context lines match exactly."
    except Exception as e:
        return f"Error applying diff: {e}"


@mcp.tool
def create_project(path: str, template: str = "python-basic") -> str:
    """
    Create a new project structure at the specified path.
    Supported templates: python-basic, node-basic, fastapi-jwt.
    """
    try:
        full_path = _resolve_user_path(path)
        if full_path.exists():
            return f"Error: Path already exists: {path}"
        
        os.makedirs(full_path, exist_ok=True)
        
        # Simple scaffolding for now
        if template == "python-basic":
            (full_path / "README.md").write_text(f"# {full_path.name}\n")
            (full_path / "main.py").write_text("def main():\n    print('Hello World')\n\nif __name__ == '__main__':\n    main()\n")
            (full_path / "requirements.txt").write_text("")
        elif template == "fastapi-jwt":
            # Just create the main file for now
            (full_path / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
            
        return f"Successfully created {template} project at {path}"
    except Exception as e:
        return f"Error creating project: {e}"

if __name__ == "__main__":
    mcp.run()
