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
def read_text_file(target_file_path: str, head: int | None = None, tail: int | None = None) -> dict[str, Any]:
    """
    Read UTF-8 text content from a file.
    REQUIRED: 'target_file_path' is the path to the file.

    Optional slicing:
    - head: first N lines
    - tail: last N lines
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
    target_file_path: str,
    exact_text_to_replace: str,
    new_text_content: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Replace text in a file.
    
    REQUIRED: 'target_file_path' is the path to the file.
    REQUIRED: 'exact_text_to_replace' is the EXACT block of text to find.
    REQUIRED: 'new_text_content' is the replacement text.
    """
    # Map to internal logic
    path = target_file_path
    old_text = exact_text_to_replace
    new_text = new_text_content

    if not path:
        raise ValueError(
            "Missing required argument: 'target_file_path'. "
            "Also check: use 'exact_text_to_replace', not 'old_text' or 'old_content'."
        )

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

    write_file(target_file_path=path, content=updated, overwrite=True)
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


@mcp.tool
def bash_exec(
    command: str,
    cwd: str | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    """
    Execute a shell command and return its output.

    - Output is capped at 50 000 characters (stdout + stderr combined).
    - Timeout default is 30 s; max is 120 s.
    - A small set of obviously destructive commands is unconditionally blocked.
    - The working directory defaults to the first allowed directory (or repo root).

    Use for: running tests, git commands, build scripts, inspecting processes.
    Do NOT use for: interactive programs, long-running daemons (use & to background).
    """
    import subprocess

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

    import time
    t0 = time.monotonic()
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ},
        )
        elapsed = time.monotonic() - t0
        combined = result.stdout + result.stderr
        total_bytes = len(combined.encode("utf-8", errors="replace"))
        truncated = total_bytes > _MAX_OUTPUT_CHARS
        if truncated:
            head = combined[:_MAX_OUTPUT_CHARS // 2]
            tail = combined[-(min(_MAX_OUTPUT_CHARS // 10, 5000)):]
            combined = (
                head
                + f"\n\n[...{total_bytes - len(head.encode()) - len(tail.encode())} bytes omitted...]\n\n"
                + tail
            )
        header = f"[exit:{result.returncode} | elapsed:{elapsed:.1f}s | {total_bytes} bytes]\n"
        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "output": header + combined,
            "truncated": truncated,
            "elapsed_seconds": round(elapsed, 2),
        }
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - t0
        return {"ok": False, "error": f"Command timed out after {timeout}s (elapsed: {elapsed:.1f}s)"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


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

_SYMBOL_PATTERNS = [
    # Python
    (r"^\s*(async\s+)?def\s+({query})\s*\(", "function"),
    (r"^\s*class\s+({query})\s*[\(:]", "class"),
    # JavaScript / TypeScript
    (r"^\s*(export\s+)?(async\s+)?function\s+({query})\s*\(", "function"),
    (r"^\s*(export\s+)?(const|let|var)\s+({query})\s*=", "variable"),
    (r"^\s*(export\s+)?(class|interface|type)\s+({query})\b", "class"),
    # Rust
    (r"^\s*(pub\s+)?(async\s+)?fn\s+({query})\s*[\(<]", "function"),
    (r"^\s*(pub\s+)?(struct|enum|impl|trait)\s+({query})\b", "class"),
    # Go
    (r"^\s*func\s+\(?.*?\)?\s*({query})\s*\(", "function"),
    (r"^\s*type\s+({query})\s+(struct|interface)", "class"),
    # Shell / generic variable assignment
    (r"^({query})\s*\(\)\s*\{{", "function"),
]


@mcp.tool
def search_symbols(
    query: str,
    file_glob: str = "*",
    max_results: int = 20,
) -> dict[str, Any]:
    """
    Search for function, class, method, or variable definitions across the codebase.

    Uses ripgrep when available; falls back to pure Python.

    Args:
        query: Symbol name to search for (exact match, case-sensitive).
        file_glob: Glob to restrict files, e.g. '*.py', '*.ts'. Defaults to all files.
        max_results: Maximum results to return (cap 100).

    Returns a list of matches with file, line number, kind (function/class/variable), and the matching line.
    """
    import re
    import subprocess

    if not query or not query.strip():
        return {"ok": False, "error": "query must be a non-empty symbol name", "matches": []}

    q = re.escape(query.strip())
    max_results = min(int(max_results), 100)

    search_root = POLICY.get_allowed_dirs()[0]

    # Build a combined regex that matches any definition pattern containing the query.
    combined_pattern = "|".join(
        pat.replace("{query}", q) for pat, _ in _SYMBOL_PATTERNS
    )

    rg = shutil.which("rg")
    raw_matches: list[dict[str, Any]] = []

    if rg:
        cmd = [
            rg, "--json", "-m", str(max_results * 3),
            "--glob", file_glob,
            "--max-filesize", "512K",
            combined_pattern, str(search_root),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            for line in proc.stdout.splitlines():
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "match":
                        data = obj["data"]
                        raw_matches.append({
                            "file": _to_relative_display(Path(data["path"]["text"])),
                            "line": data["line_number"],
                            "content": data["lines"]["text"].rstrip("\n"),
                        })
                except (json.JSONDecodeError, KeyError):
                    continue
        except Exception:
            pass

    if not raw_matches:
        # Pure Python fallback
        import re as _re
        import fnmatch as _fn
        pat_re = _re.compile(combined_pattern)
        glob_re = _re.compile(_fn.translate(file_glob))
        for dirpath, dirnames, filenames in os.walk(str(search_root)):
            dirnames[:] = [d for d in dirnames if d not in _SYMBOL_SKIP_DIRS]
            for fname in filenames:
                if not glob_re.match(fname):
                    continue
                fpath = Path(dirpath) / fname
                try:
                    for lineno, text in enumerate(fpath.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                        if pat_re.search(text):
                            raw_matches.append({
                                "file": _to_relative_display(fpath),
                                "line": lineno,
                                "content": text.rstrip("\n"),
                            })
                            if len(raw_matches) >= max_results * 3:
                                break
                except OSError:
                    continue
                if len(raw_matches) >= max_results * 3:
                    break

    # Annotate with inferred kind
    import re as _re2
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for m in raw_matches:
        key = (m["file"], m["line"])
        if key in seen:
            continue
        seen.add(key)
        kind = "symbol"
        for pat, k in _SYMBOL_PATTERNS:
            if _re2.search(pat.replace("{query}", q), m["content"]):
                kind = k
                break
        results.append({
            "name": query,
            "kind": kind,
            "file": m["file"],
            "line": m["line"],
            "snippet": m["content"].strip(),
        })
        if len(results) >= max_results:
            break

    return {"ok": True, "matches": results, "count": len(results), "query": query}


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


if __name__ == "__main__":
    mcp.run()
