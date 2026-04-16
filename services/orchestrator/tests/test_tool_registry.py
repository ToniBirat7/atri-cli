"""Tests for ToolRegistry namespacing, routing, and risk-tier behavior."""

from tool_registry import ToolRegistry


def test_register_single_server_creates_plain_and_namespaced_aliases():
    registry = ToolRegistry()
    registry.register_tools_from_mcp_discovery(
        "local-mcp",
        [
            {
                "name": "read_file",
                "description": "Read file",
                "inputSchema": {"type": "object", "properties": {}},
            }
        ],
    )

    assert registry.get_tool("read_file") is not None
    assert registry.get_tool("local-mcp.read_file") is not None
    assert registry.resolve_tool_call("read_file") == ("local-mcp", "read_file")
    assert registry.resolve_tool_call("local-mcp.read_file") == ("local-mcp", "read_file")


def test_register_multi_server_collision_keeps_namespaced_aliases():
    registry = ToolRegistry()

    shared_tool = {
        "name": "read_file",
        "description": "Read file",
        "inputSchema": {"type": "object", "properties": {}},
    }

    registry.register_tools_from_mcp_discovery("server-a", [shared_tool])
    registry.register_tools_from_mcp_discovery("server-b", [shared_tool])

    # Plain alias remains bound to first server to preserve backwards compatibility.
    assert registry.resolve_tool_call("read_file") == ("server-a", "read_file")

    # Namespaced aliases allow deterministic routing for both servers.
    assert registry.resolve_tool_call("server-a.read_file") == ("server-a", "read_file")
    assert registry.resolve_tool_call("server-b.read_file") == ("server-b", "read_file")


def test_risk_tier_inference_from_tool_name():
    registry = ToolRegistry()
    registry.register_tools_from_mcp_discovery(
        "local-mcp",
        [
            {"name": "list_directory", "description": "List", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "write_file", "description": "Write", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "delete_file", "description": "Delete", "inputSchema": {"type": "object", "properties": {}}},
        ],
    )

    assert registry.get_tool("list_directory").risk_tier == "green"
    assert registry.get_tool("write_file").risk_tier == "yellow"
    assert registry.get_tool("delete_file").risk_tier == "red"
