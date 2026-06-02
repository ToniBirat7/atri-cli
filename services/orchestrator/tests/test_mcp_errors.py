"""Tests for MCPOrchestrator error classification (server vs tool context)."""
import asyncio
import os
import sys

_ORCH_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ORCH_DIR not in sys.path:
    sys.path.insert(0, _ORCH_DIR)

from mcp_orchestrator import MCPOrchestrator


def _detail(exc, context):
    return MCPOrchestrator()._error_detail_from_exception(exc, context=context)


def test_tool_context_file_not_found():
    d = _detail(FileNotFoundError("File not found: x.py"), "tool")
    assert d.code == "MCP_FILE_NOT_FOUND"
    assert d.retryable is False


def test_tool_context_value_error():
    d = _detail(ValueError("exact_text_to_replace not found"), "tool")
    assert d.code == "MCP_TOOL_INVALID_INPUT"
    assert d.retryable is False


def test_tool_context_generic_is_retryable():
    d = _detail(RuntimeError("transient"), "tool")
    assert d.code == "MCP_TOOL_EXECUTION_ERROR"
    assert d.retryable is True


def test_server_context_unchanged():
    # Server/init context keeps the original semantics.
    d = _detail(FileNotFoundError("server binary missing"), "server")
    assert d.code == "MCP_SERVER_COMMAND_NOT_FOUND"
    d2 = _detail(ValueError("bad config"), "server")
    assert d2.code == "MCP_INVALID_CONFIGURATION"


def test_permission_denied_both_contexts():
    for ctx in ("tool", "server"):
        d = _detail(PermissionError("Access denied"), ctx)
        assert d.code == "MCP_PERMISSION_DENIED"
        assert d.retryable is False


def test_timeout_is_retryable():
    d = _detail(asyncio.TimeoutError(), "tool")
    assert d.code == "MCP_TOOL_TIMEOUT"
    assert d.retryable is True
