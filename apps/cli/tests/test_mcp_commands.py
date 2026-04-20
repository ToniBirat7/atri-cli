"""Tests for MCP CLI commands."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from tarbar_cli.main import _mcp_list_tools, _mcp_status, _mcp_refresh, _mcp_reconnect, _mcp_deferred


def test_mcp_list_tools_formats_output(monkeypatch):
    """Test that mcp tools command formats tool listings."""
    mock_client = Mock()
    mock_client.request_json.return_value = {
        "tools": [
            {
                "name": "read_file",
                "description": "Read a file",
                "server": "filesystem",
                "category": "io",
            },
            {
                "name": "bash",
                "description": "Run bash commands",
                "server": "shell",
                "category": "execution",
            },
        ],
        "total": 2,
    }

    output_lines = []

    def mock_print(*args, **kwargs):
        output_lines.append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr("builtins.print", mock_print)
    _mcp_list_tools(mock_client)

    # Check that the output contains expected tool info
    output = "\n".join(output_lines)
    assert "read_file" in output
    assert "bash" in output
    assert "filesystem" in output
    assert "shell" in output
    mock_client.request_json.assert_called_once_with("GET", "/tools")


def test_mcp_list_tools_handles_empty_list(monkeypatch):
    """Test that mcp tools command handles empty tool list gracefully."""
    mock_client = Mock()
    mock_client.request_json.return_value = {"tools": [], "total": 0}

    output_lines = []

    def mock_print(*args, **kwargs):
        output_lines.append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr("builtins.print", mock_print)
    _mcp_list_tools(mock_client)

    output = "\n".join(output_lines)
    assert "No tools available" in output


def test_mcp_status_displays_server_health(monkeypatch):
    """Test that mcp status command displays MCP server health."""
    mock_client = Mock()
    mock_client.request_json.return_value = {
        "status": "healthy",
        "llm_connected": True,
        "mcp_servers": {
            "filesystem": {"status": "connected"},
            "shell": {"status": "connected"},
        },
    }

    output_lines = []

    def mock_print(*args, **kwargs):
        output_lines.append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr("builtins.print", mock_print)
    _mcp_status(mock_client)

    output = "\n".join(output_lines)
    assert "healthy" in output
    assert "LLM connected" in output
    assert "filesystem" in output
    assert "shell" in output
    mock_client.request_json.assert_called_once_with("GET", "/health")


def test_mcp_status_handles_no_servers(monkeypatch):
    """Test that mcp status command handles case with no MCP servers configured."""
    mock_client = Mock()
    mock_client.request_json.return_value = {
        "status": "degraded",
        "llm_connected": False,
        "mcp_servers": {},
    }

    output_lines = []

    def mock_print(*args, **kwargs):
        output_lines.append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr("builtins.print", mock_print)
    _mcp_status(mock_client)

    output = "\n".join(output_lines)
    assert "No MCP servers configured" in output


def test_mcp_refresh_displays_results(monkeypatch):
    """Test that mcp refresh command displays discovery results."""
    mock_client = Mock()
    mock_client.request_json.return_value = {
        "status": "success",
        "error_code": None,
        "total_discovered": 15,
        "servers": {
            "filesystem": 10,
            "shell": 5,
        },
        "refresh_metadata": {
            "filesystem": {"source": "fresh"},
            "shell": {"source": "fresh"},
        },
    }

    output_lines = []

    def mock_print(*args, **kwargs):
        output_lines.append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr("builtins.print", mock_print)
    _mcp_refresh(mock_client, use_cache=False, clear_cache=False)

    output = "\n".join(output_lines)
    assert "success" in output
    assert "15" in output
    assert "filesystem" in output
    assert "shell" in output
    mock_client.request_json.assert_called_once_with(
        "POST",
        "/tools/refresh?force_refresh=true&clear_cache=false",
    )


def test_mcp_refresh_handles_partial_failure(monkeypatch):
    """Test that mcp refresh command handles partial failures."""
    mock_client = Mock()
    mock_client.request_json.return_value = {
        "status": "partial_failure",
        "error_code": "MCP_REFRESH_PARTIAL_FAILURE",
        "total_discovered": 10,
        "servers": {
            "filesystem": 10,
            "shell": 0,
        },
        "refresh_metadata": {
            "filesystem": {"source": "fresh"},
            "shell": {
                "source": "error",
                "error_code": "MCP_INTERNAL_ERROR",
                "recommended_fix": "Inspect orchestrator logs",
            },
        },
    }

    output_lines = []

    def mock_print(*args, **kwargs):
        output_lines.append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr("builtins.print", mock_print)
    _mcp_refresh(mock_client, use_cache=False, clear_cache=False)

    output = "\n".join(output_lines)
    assert "partial_failure" in output
    assert "10" in output
    assert "MCP_REFRESH_PARTIAL_FAILURE" in output


def test_mcp_reconnect_success(monkeypatch):
    """Test successful MCP server reconnection."""
    mock_client = Mock()
    mock_client.request_json.return_value = {
        "status": "reconnected",
        "success": True,
        "error_code": None,
        "reason": None,
        "attempts_used": 1,
        "attempts_remaining": 4,
        "next_retry_after_seconds": None,
        "recommended_fix": None,
    }

    output_lines = []

    def mock_print(*args, **kwargs):
        output_lines.append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr("builtins.print", mock_print)
    _mcp_reconnect(mock_client, "filesystem")

    output = "\n".join(output_lines)
    assert "reconnected" in output or "Successfully" in output
    mock_client.request_json.assert_called_once_with("POST", "/mcp/reconnect", {"server": "filesystem"})


def test_mcp_reconnect_failure(monkeypatch):
    """Test failed MCP server reconnection."""
    mock_client = Mock()
    mock_client.request_json.return_value = {
        "status": "backoff_active",
        "success": False,
        "error_code": "MCP_RECONNECT_BACKOFF_ACTIVE",
        "reason": "Reconnect is temporarily delayed by backoff policy",
        "attempts_used": 2,
        "attempts_remaining": 3,
        "next_retry_after_seconds": 1.25,
        "recommended_fix": "Wait for backoff window and retry",
    }

    output_lines = []

    def mock_print(*args, **kwargs):
        output_lines.append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr("builtins.print", mock_print)
    _mcp_reconnect(mock_client, "shell")

    output = "\n".join(output_lines)
    assert "Failed" in output or "failed" in output
    assert "MCP_RECONNECT_BACKOFF_ACTIVE" in output


def test_mcp_deferred_enable(monkeypatch):
    """Test enabling deferred discovery."""
    mock_client = Mock()
    mock_client.request_json.return_value = {
        "status": "configured",
        "enabled": True,
    }

    output_lines = []

    def mock_print(*args, **kwargs):
        output_lines.append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr("builtins.print", mock_print)
    _mcp_deferred(mock_client, "filesystem", True)

    output = "\n".join(output_lines)
    assert "configured" in output
    assert "filesystem" in output
    mock_client.request_json.assert_called_once_with(
        "POST", "/mcp/deferred-discovery", {"server": "filesystem", "enabled": True}
    )


def test_mcp_deferred_disable(monkeypatch):
    """Test disabling deferred discovery."""
    mock_client = Mock()
    mock_client.request_json.return_value = {
        "status": "configured",
        "enabled": False,
    }

    output_lines = []

    def mock_print(*args, **kwargs):
        output_lines.append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr("builtins.print", mock_print)
    _mcp_deferred(mock_client, "shell", False)

    output = "\n".join(output_lines)
    assert "shell" in output

