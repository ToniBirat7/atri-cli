"""
Tool Registry for normalization and schema translation.

Maintains a registry of available tools from MCP servers.
Translates MCP tool schemas to OpenAI-compatible JSON Schema format.
Provides tool lookup and validation.

Phase 1: Basic registry with schema translation.
Phase 6: Tool access control and risk tiers.
"""

from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class Tool:
    """Normalized tool representation."""
    name: str
    description: str
    input_schema: Dict[str, Any]
    server_name: str
    source_name: Optional[str] = None
    category: Optional[str] = None
    risk_tier: str = "green"  # green, yellow, red (Phase 6+)


class ToolRegistry:
    """
    Central registry of tools from MCP servers.
    
    Responsibilities:
    - Register tools from MCP server discovery
    - Translate MCP schemas to OpenAI format
    - Provide tool lookup by name
    - Generate tool lists for LLM (Phase 1)
    - Enforce access control (Phase 6)
    """

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._server_tools: Dict[str, List[str]] = {}  # server_name -> [tool_names]
        self._tool_routes: Dict[str, Tuple[str, str]] = {}  # exposed_name -> (server_name, source_name)

    def register_tool(self, tool: Tool) -> None:
        """Register a tool in the registry."""
        if tool.name in self._tools:
            logger.warning(f"Tool {tool.name} already registered, updating")
        
        self._tools[tool.name] = tool
        self._tool_routes[tool.name] = (tool.server_name, tool.source_name or tool.name)
        
        if tool.server_name not in self._server_tools:
            self._server_tools[tool.server_name] = []
        
        if tool.name not in self._server_tools[tool.server_name]:
            self._server_tools[tool.server_name].append(tool.name)
        
        logger.info(f"Registered tool: {tool.name} from {tool.server_name}")

    def _register_alias(self, alias_name: str, tool: Tool) -> None:
        """Register an additional alias for a tool route without duplicating source metadata."""
        alias_tool = Tool(
            name=alias_name,
            description=tool.description,
            input_schema=tool.input_schema,
            server_name=tool.server_name,
            source_name=tool.source_name,
            category=tool.category,
            risk_tier=tool.risk_tier,
        )
        self.register_tool(alias_tool)

    def register_tools_from_mcp_discovery(
        self,
        server_name: str,
        mcp_tools: List[Dict[str, Any]]
    ) -> None:
        """
        Register multiple tools from MCP server discovery response.

        Args:
            server_name: Name of the MCP server
            mcp_tools: List of tools from MCP ListTools response
        """
        for mcp_tool in mcp_tools:
            base_tool = self._translate_mcp_tool(mcp_tool, server_name)
            namespaced_name = f"{server_name}.{base_tool.source_name or base_tool.name}"

            # Always register namespaced form to avoid collisions across servers.
            self._register_alias(namespaced_name, base_tool)

            # Register plain alias only when unique to preserve backward compatibility.
            plain_name = base_tool.source_name or base_tool.name
            if plain_name not in self._tools:
                self._register_alias(plain_name, base_tool)
            else:
                logger.info(
                    "Skipping plain tool alias due to name collision: %s (server=%s)",
                    plain_name,
                    server_name,
                )

    def _translate_mcp_tool(self, mcp_tool: Dict[str, Any], server_name: str) -> Tool:
        """
        Translate MCP tool schema to normalized Tool format.

        MCP schema format (JSON Schema compatible):
        {
            "name": "tool_name",
            "description": "...",
            "inputSchema": {
                "type": "object",
                "properties": {...},
                "required": [...]
            }
        }

        Returns:
            Normalized Tool object
        """
        tool_name = mcp_tool.get("name", "unknown")
        return Tool(
            name=tool_name,
            description=mcp_tool.get("description", ""),
            input_schema=mcp_tool.get("inputSchema", {
                "type": "object",
                "properties": {}
            }),
            server_name=server_name,
            source_name=tool_name,
            risk_tier=self._infer_risk_tier(tool_name),
        )

    def _infer_risk_tier(self, tool_name: str) -> str:
        """Infer a coarse risk tier from tool name semantics."""
        lowered = tool_name.lower()
        red_signals = ("delete", "remove", "destroy", "shutdown", "exec", "shell", "format")
        yellow_signals = ("write", "edit", "move", "rename", "set_", "create")

        if any(signal in lowered for signal in red_signals):
            return "red"
        if any(signal in lowered for signal in yellow_signals):
            return "yellow"
        return "green"

    def resolve_tool_call(self, tool_name: str) -> Tuple[str, str]:
        """Resolve an exposed tool name to (server_name, source_tool_name)."""
        route = self._tool_routes.get(tool_name)
        if route:
            return route

        if "." in tool_name:
            server_name, source_name = tool_name.split(".", 1)
            if server_name in self._server_tools:
                return server_name, source_name

        raise ValueError(f"Tool not found in registry: {tool_name}")

    def get_tool(self, name: str) -> Optional[Tool]:
        """Get tool by name."""
        return self._tools.get(name)

    def get_tools_by_server(self, server_name: str) -> List[Tool]:
        """Get all tools from a specific server."""
        tool_names = self._server_tools.get(server_name, [])
        return [self._tools[name] for name in tool_names if name in self._tools]

    def list_all_tools(self) -> List[Tool]:
        """List all registered tools."""
        return list(self._tools.values())

    def to_openai_format(self, tools: Optional[List[Tool]] = None) -> List[Dict[str, Any]]:
        """
        Convert tools to OpenAI-compatible format for chat completions.

        Format:
        {
            "type": "function",
            "function": {
                "name": "tool_name",
                "description": "...",
                "parameters": {
                    "type": "object",
                    "properties": {...},
                    "required": [...]
                }
            }
        }

        Args:
            tools: List of tools to convert (if None, converts all)

        Returns:
            List of tools in OpenAI format
        """
        tools_to_convert = tools or self.list_all_tools()
        
        # Deduplicate by (server, source_name) to avoid passing both 'tool' and 'server.tool' to LLM
        unique_tools: Dict[Tuple[str, str], Tool] = {}
        for tool in tools_to_convert:
            key = (tool.server_name, tool.source_name or tool.name)
            existing = unique_tools.get(key)
            if not existing or len(tool.name) < len(existing.name):
                unique_tools[key] = tool
        
        result = []
        for tool in unique_tools.values():
            result.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                }
            })
        
        return result

    def clear(self) -> None:
        """Clear all registered tools."""
        self._tools.clear()
        self._server_tools.clear()
        self._tool_routes.clear()
        logger.info("Tool registry cleared")

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        return f"ToolRegistry({len(self._tools)} tools)"
