"""
MCP Client Orchestrator.

Manages lifecycle of MCP server connections and tool execution routing.
Handles:
- MCP client initialization and discovery
- Tool discovery and registry update
- Tool call routing and execution
- Error handling and resilience (Phase 5+)

Phase 1: Single MCP server support, basic discovery and tool execution.
Phase 4: Multi-server support with namespaced tool routing.
Phase 5: Retry logic, circuit-breaker, timeout handling.
"""

from typing import Dict, List, Any, Optional
import json
import logging
from dataclasses import dataclass
import asyncio
import inspect
import importlib.util
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""
    name: str
    command: str  # e.g., "fastmcp run services/mcp/main.py:mcp"
    transport: str = "stdio"  # stdio, sse, websocket


class MCPOrchestrator:
    """
    Orchestrator for MCP server lifecycle and tool execution.
    
    Phase 1: Single server support.
    Phase 4: Multi-server support with tool namespacing.
    """

    def __init__(self):
        self._servers: Dict[str, Any] = {}  # server_name -> client
        self._server_configs: Dict[str, MCPServerConfig] = {}

    def _try_load_local_module(self, config: MCPServerConfig) -> Optional[Any]:
        """Load local MCP Python module for in-process tool execution fallback."""
        command = config.command
        if "services/mcp/main.py" not in command:
            return None

        module_path = (Path(__file__).resolve().parent.parent / "mcp" / "main.py").resolve()
        if not module_path.exists():
            logger.warning(f"Local MCP module not found at {module_path}")
            return None

        spec = importlib.util.spec_from_file_location("tarbar_local_mcp", str(module_path))
        if spec is None or spec.loader is None:
            logger.warning("Failed to create import spec for local MCP module")
            return None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    async def initialize_server(self, config: MCPServerConfig) -> None:
        """
        Initialize connection to an MCP server.

        For Phase 1: Basic STDIO transport initialization.
        For Phase 4: Support multiple transports (SSE, WebSocket).

        Args:
            config: MCP server configuration
        """
        logger.info(f"Initializing MCP server: {config.name}")
        self._server_configs[config.name] = config

        module = self._try_load_local_module(config)
        if module is not None:
            self._servers[config.name] = {
                "status": "initialized",
                "command": config.command,
                "transport": config.transport,
                "mode": "inprocess-module",
                "module": module,
            }
            logger.info(f"MCP server {config.name} initialized in in-process mode")
            return

        # Placeholder metadata for future MCP SDK client mode
        self._servers[config.name] = {
            "status": "initialized",
            "command": config.command,
            "transport": config.transport,
            "mode": "metadata-only",
        }
        logger.info(f"MCP server {config.name} initialized")

    async def discover_tools(self, server_name: str) -> List[Dict[str, Any]]:
        """
        Discover available tools from an MCP server via ListTools.

        Returns:
            List of tools in MCP format
        """
        if server_name not in self._servers:
            raise ValueError(f"Server {server_name} not initialized")
        server = self._servers[server_name]
        if server.get("mode") == "inprocess-module":
            module = server["module"]
            tools: list[dict[str, Any]] = []
            for name, obj in inspect.getmembers(module, inspect.isfunction):
                if name.startswith("_"):
                    continue
                tools.append(
                    {
                        "name": name,
                        "description": (obj.__doc__ or "").strip(),
                        "inputSchema": {
                            "type": "object",
                            "properties": {},
                        },
                    }
                )
            return tools

        # Placeholder for future MCP SDK mode
        logger.info(f"Discovering tools from {server_name}")
        return []

    async def execute_tool(
        self,
        server_name: str,
        tool_name: str,
        tool_input: Dict[str, Any],
        timeout_seconds: int = 10,
    ) -> str:
        """
        Execute a tool on an MCP server.

        Args:
            server_name: Name of the MCP server
            tool_name: Name of the tool to execute
            tool_input: Input arguments for the tool
            timeout_seconds: Execution timeout

        Returns:
            Tool execution result as string

        Raises:
            TimeoutError: If tool execution exceeds timeout
            ValueError: If server or tool not found
        """
        if server_name not in self._servers:
            raise ValueError(f"Server {server_name} not initialized")

        logger.info(f"Executing {server_name}.{tool_name}({tool_input})")

        server = self._servers[server_name]
        if server.get("mode") == "inprocess-module":
            module = server["module"]
            fn = getattr(module, tool_name, None)
            if fn is None or not callable(fn):
                raise ValueError(f"Tool not found: {tool_name}")

            async def _invoke() -> Any:
                if inspect.iscoroutinefunction(fn):
                    return await fn(**tool_input)
                return await asyncio.to_thread(fn, **tool_input)

            result = await asyncio.wait_for(_invoke(), timeout=timeout_seconds)
            if isinstance(result, (dict, list)):
                return json.dumps(result, ensure_ascii=False)
            return str(result)

        # Placeholder for future MCP SDK mode
        return f"Tool {tool_name} executed"

    async def shutdown_server(self, server_name: str) -> None:
        """Gracefully shutdown an MCP server connection."""
        if server_name in self._servers:
            logger.info(f"Shutting down MCP server: {server_name}")
            # Phase 2: Implement graceful close
            del self._servers[server_name]
            logger.info(f"MCP server {server_name} shut down")

    async def shutdown_all(self) -> None:
        """Shutdown all MCP server connections."""
        for server_name in list(self._servers.keys()):
            await self.shutdown_server(server_name)

    def get_server_status(self) -> Dict[str, Any]:
        """Get status of all managed MCP servers."""
        return {
            server_name: {
                "status": server_info.get("status", "unknown"),
                "mode": server_info.get("mode", "unknown"),
            }
            for server_name, server_info in self._servers.items()
        }

    def __repr__(self) -> str:
        return f"MCPOrchestrator({len(self._servers)} servers)"
