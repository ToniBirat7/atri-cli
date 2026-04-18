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
import shlex

logger = logging.getLogger(__name__)


class MCPOrchestratorError(Exception):
    """Base error for MCP orchestration failures."""


class MCPServerNotInitializedError(MCPOrchestratorError):
    """Raised when a requested server has not been initialized."""


class MCPToolNotFoundError(MCPOrchestratorError):
    """Raised when a requested tool does not exist on a server."""


class MCPToolExecutionTimeoutError(MCPOrchestratorError):
    """Raised when a tool execution exceeds its timeout."""


class MCPToolExecutionError(MCPOrchestratorError):
    """Raised when a tool execution fails."""


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
    Phase 5: Reconnection/backoff and deferred tool discovery.
    """

    def __init__(self):
        self._servers: Dict[str, Any] = {}  # server_name -> client
        self._server_configs: Dict[str, MCPServerConfig] = {}
        # Phase 5: Resilience tracking
        self._server_failures: Dict[str, int] = {}  # server_name -> failure count
        self._server_last_retry: Dict[str, float] = {}  # server_name -> timestamp
        self._deferred_discovery: Dict[str, bool] = {}  # server_name -> deferred flag
        self._deferred_tools_cache: Dict[str, List[Dict[str, Any]]] = {}  # server_name -> tools
        # Configuration
        self.MAX_TOOLS_BEFORE_DEFERRED = 50  # Defer if > 50 tools
        self.MAX_RETRY_ATTEMPTS = 5
        self.INITIAL_BACKOFF_SECONDS = 1
        self.MAX_BACKOFF_SECONDS = 60

    def _try_load_local_module(self, config: MCPServerConfig) -> Optional[Any]:
        """Load local MCP Python module for in-process tool execution fallback."""
        command = config.command
        if "services/mcp/main.py" not in command:
            return None

        module_path = self._resolve_local_module_path(command)
        if module_path is None:
            logger.warning("Local MCP module not found for command: %s", command)
            return None

        spec = importlib.util.spec_from_file_location("tarbar_local_mcp", str(module_path))
        if spec is None or spec.loader is None:
            logger.warning("Failed to create import spec for local MCP module")
            return None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _resolve_local_module_path(self, command: str) -> Optional[Path]:
        """Resolve services/mcp/main.py path for both container and local executions."""
        try:
            tokens = shlex.split(command)
        except Exception:
            tokens = command.split()

        command_path: Optional[str] = None
        for token in tokens:
            if "services/mcp/main.py" in token:
                command_path = token.split(":", 1)[0]
                break

        if command_path is None:
            command_path = "services/mcp/main.py"

        path_candidate = Path(command_path)
        candidates: list[Path] = []
        if path_candidate.is_absolute():
            candidates.append(path_candidate)
        else:
            candidates.extend(
                [
                    Path.cwd() / path_candidate,
                    Path("/app") / path_candidate,
                    Path(__file__).resolve().parent.parent / "mcp" / "main.py",
                ]
            )

        # Preserve candidate order while deduplicating.
        seen: set[Path] = set()
        ordered_candidates: list[Path] = []
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            ordered_candidates.append(resolved)

        for resolved in ordered_candidates:
            if resolved.exists() and resolved.is_file():
                return resolved

        return None

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
        max_retries: int = 2,
    ) -> str:
        """
        Execute a tool on an MCP server with retry logic.

        Args:
            server_name: Name of the MCP server
            tool_name: Name of the tool to execute
            tool_input: Input arguments for the tool
            timeout_seconds: Execution timeout
            max_retries: Maximum retry attempts on failure

        Returns:
            Tool execution result as string

        Raises:
            TimeoutError: If tool execution exceeds timeout
            ValueError: If server or tool not found
        """
        if server_name not in self._servers:
            raise MCPServerNotInitializedError(f"Server {server_name} not initialized")

        logger.info(f"Executing {server_name}.{tool_name}({tool_input})")

        server = self._servers[server_name]
        if server.get("mode") == "inprocess-module":
            module = server["module"]
            fn = getattr(module, tool_name, None)
            if fn is None or not callable(fn):
                raise MCPToolNotFoundError(f"Tool not found: {tool_name}")

            async def _invoke() -> Any:
                if inspect.iscoroutinefunction(fn):
                    return await fn(**tool_input)
                return await asyncio.to_thread(fn, **tool_input)

            last_error: Optional[BaseException] = None
            for attempt in range(1, max_retries + 1):
                try:
                    result = await asyncio.wait_for(_invoke(), timeout=timeout_seconds)
                    if isinstance(result, (dict, list)):
                        json_result = json.dumps(result, ensure_ascii=False)
                        logger.info(f"Tool {server_name}.{tool_name} succeeded on attempt {attempt}")
                        return json_result
                    str_result = str(result)
                    logger.info(f"Tool {server_name}.{tool_name} succeeded on attempt {attempt}")
                    return str_result
                except asyncio.TimeoutError as exc:
                    last_error = exc
                    if attempt >= max_retries:
                        logger.error(
                            f"Tool {server_name}.{tool_name} timed out after {timeout_seconds}s on attempt {attempt}/{max_retries}"
                        )
                        raise MCPToolExecutionTimeoutError(
                            f"Tool {server_name}.{tool_name} timed out after {timeout_seconds}s"
                        ) from exc
                    backoff = 0.1 * attempt
                    logger.warning(
                        f"Tool {server_name}.{tool_name} timed out on attempt {attempt}/{max_retries}, retrying in {backoff}s"
                    )
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    last_error = exc
                    if attempt >= max_retries:
                        logger.error(
                            f"Tool {server_name}.{tool_name} failed on attempt {attempt}/{max_retries}: {type(exc).__name__}: {exc}"
                        )
                        raise MCPToolExecutionError(
                            f"Tool {server_name}.{tool_name} failed: {exc}"
                        ) from exc
                    backoff = 0.1 * attempt
                    logger.warning(
                        f"Tool {server_name}.{tool_name} failed on attempt {attempt}/{max_retries} ({type(exc).__name__}), retrying in {backoff}s"
                    )
                    await asyncio.sleep(backoff)

            raise MCPToolExecutionError(
                f"Tool {server_name}.{tool_name} failed after {max_retries} attempts"
            ) from last_error

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

    async def refresh_tools(self, tool_registry: 'ToolRegistry') -> Dict[str, int]:
        """
        Refresh tool discovery from all active MCP servers.
        
        Returns:
            Dict mapping server_name -> count of discovered tools
        """
        results = {}
        for server_name in self._servers.keys():
            try:
                tools = await self.discover_tools(server_name)
                tool_registry.register_tools_from_mcp_discovery(tools, server_name)
                results[server_name] = len(tools)
                logger.info(f"Refreshed {len(tools)} tools from {server_name}")
            except Exception as e:
                logger.error(f"Failed to refresh tools from {server_name}: {e}")
                results[server_name] = 0
        return results

    def _calculate_backoff_delay(self, server_name: str) -> float:
        """Calculate exponential backoff delay for a server."""
        attempts = self._server_failures.get(server_name, 0)
        if attempts >= self.MAX_RETRY_ATTEMPTS:
            return self.MAX_BACKOFF_SECONDS
        delay = self.INITIAL_BACKOFF_SECONDS * (2 ** attempts)
        return min(delay, self.MAX_BACKOFF_SECONDS)

    async def reconnect_server(self, server_name: str) -> bool:
        """
        Attempt to reconnect to a failed MCP server with exponential backoff.
        
        Returns:
            True if reconnection succeeded, False otherwise
        """
        if server_name not in self._server_configs:
            logger.error(f"Server {server_name} not in configs")
            return False

        attempts = self._server_failures.get(server_name, 0)
        if attempts >= self.MAX_RETRY_ATTEMPTS:
            logger.error(f"Server {server_name} exceeded max retry attempts ({self.MAX_RETRY_ATTEMPTS})")
            return False

        try:
            config = self._server_configs[server_name]
            await self.initialize_server(config)
            self._server_failures[server_name] = 0  # Reset on success
            logger.info(f"Successfully reconnected to server {server_name}")
            return True
        except Exception as e:
            self._server_failures[server_name] = attempts + 1
            logger.error(f"Reconnection attempt {attempts + 1} for {server_name} failed: {e}")
            return False

    def should_defer_discovery(self, tool_count: int) -> bool:
        """Check if tool discovery should be deferred based on tool count threshold."""
        return tool_count > self.MAX_TOOLS_BEFORE_DEFERRED

    async def set_deferred_discovery(self, server_name: str, deferred: bool) -> None:
        """Enable or disable deferred tool discovery for a server."""
        self._deferred_discovery[server_name] = deferred
        if not deferred and server_name in self._deferred_tools_cache:
            # Clear cache when deferral is disabled
            del self._deferred_tools_cache[server_name]
        logger.info(f"Deferred discovery for {server_name} set to {deferred}")

    async def discover_tools_lazy(
        self, server_name: str, tool_registry: 'ToolRegistry'
    ) -> List[Dict[str, Any]]:
        """
        Discover tools with deferred loading for large schemas.
        If deferred, register a stub and load on-demand.
        """
        if server_name in self._deferred_tools_cache:
            return self._deferred_tools_cache[server_name]

        tools = await self.discover_tools(server_name)
        
        if self.should_defer_discovery(len(tools)):
            self._deferred_discovery[server_name] = True
            # Cache discovered tools for lazy loading
            self._deferred_tools_cache[server_name] = tools
            logger.info(f"Deferring discovery for {server_name} ({len(tools)} tools > {self.MAX_TOOLS_BEFORE_DEFERRED})")
            # Return stub indicating deferred state
            return [{"name": f"__{server_name}_deferred__", "description": "Tools deferred for performance"}]
        
        return tools

    def get_server_status(self) -> Dict[str, Any]:
        """Get status of all managed MCP servers, including resilience info."""
        return {
            server_name: {
                "status": server_info.get("status", "unknown"),
                "mode": server_info.get("mode", "unknown"),
                "failures": self._server_failures.get(server_name, 0),
                "max_retry_attempts": self.MAX_RETRY_ATTEMPTS,
                "deferred_discovery": self._deferred_discovery.get(server_name, False),
            }
            for server_name, server_info in self._servers.items()
        }

    def __repr__(self) -> str:
        return f"MCPOrchestrator({len(self._servers)} servers)"
