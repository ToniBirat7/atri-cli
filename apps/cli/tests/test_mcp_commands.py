"""Tests for MCP CLI commands."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from tarbar_cli.main import _mcp_list_tools, _mcp_status, _mcp_refresh


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
        "total_discovered": 15,
        "servers": {
            "filesystem": 10,
            "shell": 5,
        },
    }

    output_lines = []

    def mock_print(*args, **kwargs):
        output_lines.append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr("builtins.print", mock_print)
    _mcp_refresh(mock_client)

    output = "\n".join(output_lines)
    assert "success" in output
    assert "15" in output
    assert "filesystem" in output
    assert "shell" in output
    mock_client.request_json.assert_called_once_with("POST", "/tools/refresh")


def test_mcp_refresh_handles_partial_failure(monkeypatch):
    """Test that mcp refresh command handles partial failures."""
    mock_client = Mock()
    mock_client.request_json.return_value = {
        "status": "partial_failure",
        "total_discovered": 10,
        "servers": {
            "filesystem": 10,
            "shell": 0,
        },
    }

    output_lines = []

    def mock_print(*args, **kwargs):
        output_lines.append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr("builtins.print", mock_print)
    _mcp_refresh(mock_client)

    output = "\n".join(output_lines)
    assert "partial_failure" in output
    assert "10" in output

