"""Unit tests for MCP tool sandboxing and intent detection."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Path sandbox ──────────────────────────────────────────────────────────────

def _mcp():
    """Import mcp main with repo root as allowed dir."""
    import importlib, importlib.util
    mcp_path = Path(__file__).resolve().parents[3] / "services" / "mcp" / "main.py"
    spec = importlib.util.spec_from_file_location("mcp_main", str(mcp_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mcp_mod():
    return _mcp()


def test_path_traversal_blocked(mcp_mod, tmp_path):
    """Paths outside allowed dirs must raise PermissionError."""
    with pytest.raises(PermissionError):
        mcp_mod._resolve_user_path("/etc/passwd")


def test_null_byte_blocked(mcp_mod):
    """Null bytes in paths must be rejected."""
    with pytest.raises(ValueError, match="null byte"):
        mcp_mod._resolve_user_path("some/path\x00evil")


def test_relative_path_resolves_under_allowed(mcp_mod):
    """A safe relative path must resolve inside the allowed root."""
    resolved = mcp_mod._resolve_user_path("services/orchestrator/config.py")
    assert resolved.exists()


def test_read_text_file_returns_content(mcp_mod):
    result = mcp_mod.read_text_file(target_file_path="services/orchestrator/config.py")
    assert result["content"]
    assert "OrchestratorConfig" in result["content"]


def test_read_text_file_not_found(mcp_mod):
    with pytest.raises(FileNotFoundError):
        mcp_mod.read_text_file(target_file_path="nonexistent_file_xyz.py")


def test_list_directory_returns_entries(mcp_mod):
    result = mcp_mod.list_directory(target_path="services/orchestrator")
    names = [e["name"] for e in result["entries"]]
    assert "api.py" in names
    assert "config.py" in names


def test_list_directory_not_found(mcp_mod):
    with pytest.raises(FileNotFoundError):
        mcp_mod.list_directory(target_path="nonexistent_dir_xyz")


# ── bash_exec ────────────────────────────────────────────────────────────────

def test_bash_exec_echo(mcp_mod):
    result = mcp_mod.bash_exec(command="echo hello_atri")
    assert result["ok"] is True
    assert "hello_atri" in result["output"]


def test_bash_exec_exit_code(mcp_mod):
    result = mcp_mod.bash_exec(command="exit 1")
    assert result["ok"] is False
    assert result["exit_code"] == 1


def test_bash_exec_blocks_rm_rf_root(mcp_mod):
    result = mcp_mod.bash_exec(command="rm -rf /")
    assert result["ok"] is False
    assert "Blocked" in result.get("error", "")


def test_bash_exec_python_version(mcp_mod):
    result = mcp_mod.bash_exec(command="python3 --version")
    assert result["ok"] is True
    assert "Python" in result["output"]


# ── grep_codebase ─────────────────────────────────────────────────────────────

def test_grep_codebase_finds_pattern(mcp_mod):
    result = mcp_mod.grep_codebase(pattern="OrchestratorConfig", path="services/orchestrator")
    assert result["ok"] is True
    assert result["count"] > 0
    files = [m["file"] for m in result["matches"]]
    assert any("config.py" in f for f in files)


def test_grep_codebase_no_match(mcp_mod):
    result = mcp_mod.grep_codebase(pattern="ZZZZ_TRULY_UNIQUE_NO_MATCH_4f8a1b2c", path="services/mcp")
    assert result["ok"] is True
    assert result["count"] == 0


def test_grep_codebase_skips_venv(mcp_mod):
    """Python fallback must not walk into .venv."""
    result = mcp_mod.grep_codebase(pattern="pip", path="services/orchestrator", file_glob="*.py")
    files = [m["file"] for m in result.get("matches", [])]
    assert not any(".venv" in f for f in files)


# ── todo persistence ──────────────────────────────────────────────────────────

def test_todo_write_and_read(mcp_mod, tmp_path, monkeypatch):
    """Todos written must survive a read call (file-backed)."""
    # Point todo file at a temp location
    monkeypatch.setattr(mcp_mod, "_todo_file", lambda: tmp_path / "todos.json")

    items = [
        {"content": "Write tests", "status": "pending"},
        {"content": "Fix grep perf", "status": "in_progress"},
    ]
    write_result = mcp_mod.todo_write(todos=items)
    assert write_result["ok"] is True
    assert write_result["count"] == 2

    read_result = mcp_mod.todo_read()
    assert read_result["count"] == 2
    contents = [t["content"] for t in read_result["todos"]]
    assert "Write tests" in contents
    assert "Fix grep perf" in contents


def test_todo_write_requires_content(mcp_mod):
    with pytest.raises(ValueError, match="content"):
        mcp_mod.todo_write(todos=[{"status": "pending"}])


# ── write + edit ──────────────────────────────────────────────────────────────

def test_write_and_read_roundtrip(mcp_mod, tmp_path, monkeypatch):
    """write_file → read_text_file roundtrip must preserve content."""
    # Allow tmp_path as a valid dir for this test
    target = "test_roundtrip_xyz.txt"
    content = "Hello from atri tests\nLine 2\n"

    # We can't easily add tmp_path to allowed dirs in isolation, so use the repo root
    repo = Path(__file__).resolve().parents[3]
    test_file = repo / target
    try:
        write_result = mcp_mod.write_file(target_file_path=target, content=content)
        assert write_result["ok"] is True
        read_result = mcp_mod.read_text_file(target_file_path=target)
        assert read_result["content"].strip() == content.strip()
    finally:
        if test_file.exists():
            test_file.unlink()
