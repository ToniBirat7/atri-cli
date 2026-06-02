"""Tests for agent loop intent detection — synthetic tool injection and tool correction."""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agent_loop import AgentLoop


# ── Helpers ───────────────────────────────────────────────────────────────────

class _FakeToolRegistry:
    """Minimal registry that reports all tools as resolvable."""
    def resolve_tool_call(self, name):
        return ("local-mcp", name)


_REGISTRY = _FakeToolRegistry()


async def _detect(msg: str) -> object:
    loop = AgentLoop()
    loop.state.total_tool_calls = 0
    return await loop._detect_synthetic_tool_call(
        user_message=msg,
        tool_registry=_REGISTRY,
    )


# ── read_text_file detection ──────────────────────────────────────────────────

def test_detects_read_file():
    call = asyncio.run(_detect("Read the file services/orchestrator/config.py and tell me what max_turns is."))
    assert call is not None
    assert call.tool_name == "read_text_file"
    assert "config.py" in call.tool_input["target_file_path"]


def test_detects_read_agent_loop():
    call = asyncio.run(_detect("Read services/orchestrator/agent_loop.py and summarise what _thinking_for_turn() does."))
    assert call is not None
    assert call.tool_name == "read_text_file"
    assert "agent_loop.py" in call.tool_input["target_file_path"]


def test_detects_nonexistent_file_read():
    """Even for files that don't exist, intent should map to read_text_file."""
    call = asyncio.run(_detect("Read the file services/orchestrator/nonexistent_file.py and tell me what is in it."))
    assert call is not None
    assert call.tool_name == "read_text_file"


# ── list_directory detection ──────────────────────────────────────────────────

def test_detects_list_cwd():
    call = asyncio.run(_detect("List the files in the current working directory."))
    assert call is not None
    assert call.tool_name == "list_directory"
    assert call.tool_input["target_path"] == "."


def test_detects_list_subdir():
    call = asyncio.run(_detect("List the files inside services/orchestrator/."))
    assert call is not None
    assert call.tool_name == "list_directory"


def test_detects_how_many_files():
    """'how many Python files' should map to list_directory, not hallucinate."""
    call = asyncio.run(_detect("How many Python files are in services/orchestrator/? Just give me the count."))
    assert call is not None
    assert call.tool_name == "list_directory"


def test_detects_find_files_named():
    """'find all files named *.py' is a directory listing, not grep."""
    call = asyncio.run(_detect("Find all files named '*.py' in services/mcp/ and then read main.py."))
    assert call is not None
    assert call.tool_name == "list_directory"


# ── bash_exec detection ───────────────────────────────────────────────────────

def test_detects_run_echo():
    call = asyncio.run(_detect("Run `echo 'atri test harness active'` and show me the output."))
    assert call is not None
    assert call.tool_name == "bash_exec"
    assert "echo" in call.tool_input["command"]


def test_detects_run_python_version():
    call = asyncio.run(_detect("Run `python3 --version` and tell me the Python version."))
    assert call is not None
    assert call.tool_name == "bash_exec"
    assert "python3" in call.tool_input["command"]


def test_detects_run_ls():
    call = asyncio.run(_detect("Run `ls -lh models/` and show me the model files and their sizes."))
    assert call is not None
    assert call.tool_name == "bash_exec"


# ── grep_codebase detection ───────────────────────────────────────────────────

def test_detects_grep_uses_of():
    call = asyncio.run(_detect("Search the codebase for all uses of 'thinking_mode' and list the files."))
    assert call is not None
    assert call.tool_name == "grep_codebase"
    assert call.tool_input["pattern"] == "thinking_mode"


def test_detects_grep_imports():
    call = asyncio.run(_detect("Find every file that imports 'AgentLoop'."))
    assert call is not None
    assert call.tool_name == "grep_codebase"
    assert "AgentLoop" in call.tool_input["pattern"]


def test_detects_grep_how_many_times():
    call = asyncio.run(_detect("How many times does the string 'tool_call' appear across the services/ directory?"))
    assert call is not None
    assert call.tool_name == "grep_codebase"
    assert call.tool_input["pattern"] == "tool_call"


def test_find_files_named_does_NOT_map_to_grep():
    """'find files named *.py' must NOT be confused with grep_codebase."""
    call = asyncio.run(_detect("Find all files named '*.py' in services/mcp/"))
    assert call is not None
    assert call.tool_name != "grep_codebase", "find files named should be list_directory, not grep"


# ── _correct_tool_calls_for_intent ────────────────────────────────────────────

try:
    from llm_adapter import ToolUse  # noqa: F401 — availability probe
    _HAS_TOOLUSE = True
except ImportError:
    _HAS_TOOLUSE = False


@pytest.mark.skipif(not _HAS_TOOLUSE, reason="ToolUse not importable")
def test_corrects_wrong_tool_to_bash_exec():
    from llm_adapter import ToolUse
    loop = AgentLoop()
    wrong = [ToolUse(tool_name="list_directory", tool_input={"target_path": "."}, id="c1")]
    corrected = loop._correct_tool_calls_for_intent(wrong, "Run `echo hello` and show me the output.")
    assert corrected[0].tool_name == "bash_exec"
    assert corrected[0].tool_input["command"] == "echo hello"


@pytest.mark.skipif(not _HAS_TOOLUSE, reason="ToolUse not importable")
def test_corrects_wrong_tool_to_grep():
    from llm_adapter import ToolUse
    loop = AgentLoop()
    wrong = [ToolUse(tool_name="list_directory", tool_input={}, id="c2")]
    corrected = loop._correct_tool_calls_for_intent(
        wrong, "Search the codebase for all uses of 'thinking_mode' and list the files."
    )
    assert corrected[0].tool_name == "grep_codebase"


@pytest.mark.skipif(not _HAS_TOOLUSE, reason="ToolUse not importable")
def test_find_files_named_corrects_to_list_directory():
    from llm_adapter import ToolUse
    loop = AgentLoop()
    wrong = [ToolUse(tool_name="grep_codebase", tool_input={"pattern": "*.py"}, id="c3")]
    corrected = loop._correct_tool_calls_for_intent(
        wrong, "Find all files named '*.py' in services/mcp/ and then read main.py."
    )
    assert corrected[0].tool_name == "list_directory"


@pytest.mark.skipif(not _HAS_TOOLUSE, reason="ToolUse not importable")
def test_no_correction_when_tool_already_correct():
    from llm_adapter import ToolUse
    loop = AgentLoop()
    correct = [ToolUse(tool_name="bash_exec", tool_input={"command": "echo hi"}, id="c4")]
    result = loop._correct_tool_calls_for_intent(correct, "Run `echo hi`")
    assert result[0].tool_name == "bash_exec"
