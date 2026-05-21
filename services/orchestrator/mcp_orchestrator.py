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
import time

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


@dataclass
class MCPErrorDetail:
    code: str
    message: str
    retryable: bool


@dataclass
class MCPReconnectResult:
    status: str
    success: bool
    error_code: Optional[str] = None
    reason: Optional[str] = None
    retryable: Optional[bool] = None
    attempts_used: int = 0
    attempts_remaining: int = 0
    next_retry_after_seconds: Optional[float] = None
    recommended_fix: Optional[str] = None


class MCPOrchestrator:
    """
    Orchestrator for MCP server lifecycle and tool execution.
    
    Phase 1: Single server support.
    Phase 4: Multi-server support with tool namespacing.
    Phase 5: Reconnection/backoff and deferred tool discovery.
    """

    def __init__(self):
        self._servers: Dict[str, Any] = {}  # server_name -> client
        # Phase 4.4: External MCP servers (URL-based, HTTP transport)
        self._external_servers: Dict[str, Dict[str, str]] = {}  # name -> {url, api_key}
        self._server_configs: Dict[str, MCPServerConfig] = {}
        # Phase 5: Resilience tracking
        self._server_failures: Dict[str, int] = {}  # server_name -> failure count
        self._server_last_retry: Dict[str, float] = {}  # server_name -> timestamp
        self._deferred_discovery: Dict[str, bool] = {}  # server_name -> deferred flag
        self._deferred_tools_cache: Dict[str, List[Dict[str, Any]]] = {}  # server_name -> tools
        self._tool_discovery_cache: Dict[str, Dict[str, Any]] = {}  # server_name -> {tools, cached_at}
        self._tool_schemas: Dict[str, Dict[str, Any]] = {}  # (server_name, tool_name) -> schema
        self._last_discovery_source: Dict[str, str] = {}  # server_name -> cache|fresh
        self._last_refresh_metadata: Dict[str, Dict[str, Any]] = {}  # server_name -> metadata
        self._startup_trace: Dict[str, Any] = {
            "started_at": None,
            "completed_at": None,
            "servers": {},
        }
        # Configuration
        self.MAX_TOOLS_BEFORE_DEFERRED = 50  # Defer if > 50 tools
        self.MAX_RETRY_ATTEMPTS = 5
        self.INITIAL_BACKOFF_SECONDS = 1
        self.MAX_BACKOFF_SECONDS = 60
        self.STARTUP_MAX_ATTEMPTS = 3
        self.STARTUP_INITIAL_BACKOFF_SECONDS = 1.0
        self.STARTUP_MAX_BACKOFF_SECONDS = 8.0
        self.DISCOVERY_CACHE_TTL_SECONDS = 30
        # E.3: Disk-backed tool cache path
        self._tool_disk_cache_path = Path("runtime/state/mcp_tool_cache.json")
        self._tool_disk_cache_ttl_seconds = 3600  # overridable via configure_runtime

    def _load_disk_tool_cache(self, server_name: str) -> list | None:
        """Load tool definitions from disk cache if present and not stale."""
        try:
            data = json.loads(self._tool_disk_cache_path.read_text())
            if (
                data.get("server_name") == server_name
                and self._tool_disk_cache_ttl_seconds > 0
                and time.time() - float(data.get("timestamp", 0)) < self._tool_disk_cache_ttl_seconds
            ):
                return data.get("tools", [])
        except Exception:
            pass
        return None

    def _save_disk_tool_cache(self, server_name: str, tools: list) -> None:
        """Persist tool definitions to disk for fast startup fallback."""
        try:
            self._tool_disk_cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._tool_disk_cache_path.write_text(
                json.dumps({"server_name": server_name, "timestamp": time.time(), "tools": tools})
            )
        except Exception as exc:
            logger.debug("Failed to write tool disk cache: %s", exc)

    def configure_runtime(
        self,
        *,
        startup_max_attempts: Optional[int] = None,
        startup_initial_backoff_seconds: Optional[float] = None,
        startup_max_backoff_seconds: Optional[float] = None,
        discovery_cache_ttl_seconds: Optional[int] = None,
    ) -> None:
        if startup_max_attempts is not None:
            self.STARTUP_MAX_ATTEMPTS = max(1, int(startup_max_attempts))
        if startup_initial_backoff_seconds is not None:
            self.STARTUP_INITIAL_BACKOFF_SECONDS = max(0.0, float(startup_initial_backoff_seconds))
        if startup_max_backoff_seconds is not None:
            self.STARTUP_MAX_BACKOFF_SECONDS = max(0.0, float(startup_max_backoff_seconds))
        if discovery_cache_ttl_seconds is not None:
            self.DISCOVERY_CACHE_TTL_SECONDS = max(0, int(discovery_cache_ttl_seconds))

    def reset_startup_trace(self, expected_servers: Optional[List[str]] = None) -> None:
        self._startup_trace = {
            "started_at": time.time(),
            "completed_at": None,
            "expected_servers": expected_servers or [],
            "servers": {},
        }

    def complete_startup_trace(self) -> None:
        self._startup_trace["completed_at"] = time.time()

    def get_startup_trace_summary(self) -> Dict[str, Any]:
        servers: Dict[str, Any] = self._startup_trace.get("servers", {})
        failed = [name for name, item in servers.items() if item.get("status") != "initialized"]
        initialized = [name for name, item in servers.items() if item.get("status") == "initialized"]
        recommendations = [
            item.get("recommended_fix")
            for item in servers.values()
            if item.get("recommended_fix")
        ]
        return {
            "started_at": self._startup_trace.get("started_at"),
            "completed_at": self._startup_trace.get("completed_at"),
            "expected_servers": self._startup_trace.get("expected_servers", []),
            "initialized_servers": initialized,
            "failed_servers": failed,
            "servers": servers,
            "recommendations": recommendations,
        }

    def update_startup_trace_server(self, server_name: str, **fields: Any) -> None:
        servers = self._startup_trace.setdefault("servers", {})
        current = dict(servers.get(server_name, {}))
        current.update(fields)
        servers[server_name] = current

    def _error_detail_from_exception(self, exc: BaseException) -> MCPErrorDetail:
        if isinstance(exc, asyncio.TimeoutError):
            return MCPErrorDetail(code="MCP_TOOL_TIMEOUT", message=str(exc), retryable=True)
        if isinstance(exc, FileNotFoundError):
            return MCPErrorDetail(code="MCP_SERVER_COMMAND_NOT_FOUND", message=str(exc), retryable=False)
        if isinstance(exc, PermissionError):
            return MCPErrorDetail(code="MCP_PERMISSION_DENIED", message=str(exc), retryable=False)
        if isinstance(exc, ValueError):
            return MCPErrorDetail(code="MCP_INVALID_CONFIGURATION", message=str(exc), retryable=False)
        return MCPErrorDetail(code="MCP_INTERNAL_ERROR", message=str(exc), retryable=True)

    def _recommended_fix(self, error_code: str) -> str:
        if error_code == "MCP_SERVER_COMMAND_NOT_FOUND":
            return "Verify MCP server command/path and runtime dependencies"
        if error_code == "MCP_INVALID_CONFIGURATION":
            return "Check MCP server config entries (name, command, transport)"
        if error_code == "MCP_PERMISSION_DENIED":
            return "Grant file/execute permissions for MCP module and workspace"
        if error_code == "MCP_TOOL_TIMEOUT":
            return "Increase tool timeout or reduce workload for MCP tools"
        return "Inspect orchestrator logs for MCP startup details"

    async def initialize_server_with_retry(self, config: MCPServerConfig) -> Dict[str, Any]:
        attempts = 0
        last_error: Optional[MCPErrorDetail] = None
        max_attempts = max(1, self.STARTUP_MAX_ATTEMPTS)

        while attempts < max_attempts:
            attempts += 1
            try:
                await self.initialize_server(config)
                result = {
                    "status": "initialized",
                    "attempts": attempts,
                    "error_code": None,
                    "error": None,
                    "recommended_fix": None,
                }
                self._startup_trace.setdefault("servers", {})[config.name] = result
                return result
            except Exception as exc:
                error = self._error_detail_from_exception(exc)
                last_error = error
                logger.error(
                    json.dumps(
                        {
                            "event": "mcp.server.initialize.retryable_error",
                            "server": config.name,
                            "attempt": attempts,
                            "max_attempts": max_attempts,
                            "error_code": error.code,
                            "error": error.message,
                            "retryable": error.retryable,
                        },
                        ensure_ascii=True,
                    )
                )
                if attempts >= max_attempts or not error.retryable:
                    break
                delay = min(
                    self.STARTUP_MAX_BACKOFF_SECONDS,
                    self.STARTUP_INITIAL_BACKOFF_SECONDS * (2 ** (attempts - 1)),
                )
                await asyncio.sleep(delay)

        final_error = last_error or MCPErrorDetail(
            code="MCP_INTERNAL_ERROR",
            message="Unknown startup failure",
            retryable=False,
        )
        result = {
            "status": "failed",
            "attempts": attempts,
            "error_code": final_error.code,
            "error": final_error.message,
            "recommended_fix": self._recommended_fix(final_error.code),
        }
        self._startup_trace.setdefault("servers", {})[config.name] = result
        raise MCPOrchestratorError(f"{final_error.code}: {final_error.message}")

    def clear_tool_cache(self, server_name: Optional[str] = None) -> None:
        if server_name is None:
            self._tool_discovery_cache.clear()
            return
        self._tool_discovery_cache.pop(server_name, None)

    def get_discovery_cache_status(self) -> Dict[str, Any]:
        now = time.time()
        result: Dict[str, Any] = {}
        for server_name, entry in self._tool_discovery_cache.items():
            cached_at = float(entry.get("cached_at", 0.0))
            age_seconds = max(0.0, now - cached_at)
            result[server_name] = {
                "tool_count": len(entry.get("tools", [])),
                "age_seconds": round(age_seconds, 3),
                "ttl_seconds": self.DISCOVERY_CACHE_TTL_SECONDS,
                "fresh": (
                    self.DISCOVERY_CACHE_TTL_SECONDS == 0
                    or age_seconds <= self.DISCOVERY_CACHE_TTL_SECONDS
                ),
            }
        return result

    def get_last_refresh_metadata(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._last_refresh_metadata)

    def _try_load_local_module(self, config: MCPServerConfig) -> Optional[Any]:
        """Load local MCP Python module for in-process tool execution fallback."""
        command = config.command
        if "services/mcp/main.py" not in command:
            return None

        module_path = self._resolve_local_module_path(command)
        if module_path is None:
            logger.warning("Local MCP module not found for command: %s", command)
            return None

        spec = importlib.util.spec_from_file_location("atri_local_mcp", str(module_path))
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

    async def discover_tools(self, server_name: str, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Discover available tools from an MCP server via ListTools.

        Returns:
            List of tools in MCP format
        """
        if server_name not in self._servers:
            raise ValueError(f"Server {server_name} not initialized")

        now = time.time()
        if not force_refresh and self.DISCOVERY_CACHE_TTL_SECONDS > 0:
            cache_entry = self._tool_discovery_cache.get(server_name)
            if cache_entry is not None:
                age_seconds = now - float(cache_entry.get("cached_at", 0.0))
                if age_seconds <= self.DISCOVERY_CACHE_TTL_SECONDS:
                    self._last_discovery_source[server_name] = "cache"
                    tools = list(cache_entry.get("tools", []))
                    # Ensure schema lookup is populated even on cache hits
                    for t in tools:
                        self._tool_schemas[(server_name, t["name"])] = t["inputSchema"]
                    return tools

        server = self._servers[server_name]
        if server.get("mode") == "inprocess-module":
            module = server["module"]
            tools: list[dict[str, Any]] = []
            
            # 1. Try to use native FastMCP/MCP object if available
            mcp_obj = getattr(module, "mcp", None)
            if mcp_obj and (hasattr(mcp_obj, "list_tools") or hasattr(mcp_obj, "get_tools")):
                try:
                    # FastMCP >= 2.x uses get_tools() (async, returns dict {name: Tool})
                    # FastMCP < 2.x uses list_tools() (sync/async, returns list)
                    if hasattr(mcp_obj, "get_tools"):
                        raw = mcp_obj.get_tools()
                        if inspect.isawaitable(raw):
                            raw = await raw
                        # get_tools returns dict {name: Tool} — convert to list
                        if isinstance(raw, dict):
                            mcp_tools = list(raw.values())
                        else:
                            mcp_tools = list(raw)
                    else:
                        mcp_tools = mcp_obj.list_tools()
                        if inspect.isawaitable(mcp_tools):
                            mcp_tools = await mcp_tools

                    for t in mcp_tools:
                        # Convert to dict if it's a model
                        t_dict = t.model_dump() if hasattr(t, "model_dump") else (t if isinstance(t, dict) else vars(t))
                        tools.append({
                            "name": t_dict.get("name"),
                            "description": t_dict.get("description", ""),
                            "inputSchema": (
                            t_dict.get("inputSchema")
                            or t_dict.get("input_schema")
                            or t_dict.get("parameters")
                            or {"type": "object", "properties": {}}
                        )
                        })
                    if tools:
                        # Update schema lookup for coercion
                        for t in tools:
                             self._tool_schemas[(server_name, t["name"])] = t["inputSchema"]

                        self._tool_discovery_cache[server_name] = {"tools": tools, "cached_at": now}
                        # E.3: persist to disk for next-startup fallback
                        self._save_disk_tool_cache(server_name, tools)
                        return tools
                except asyncio.TimeoutError:
                    logger.warning("Tool discovery timed out for %s — falling back to disk cache", server_name)
                    cached = self._load_disk_tool_cache(server_name)
                    if cached:
                        for t in cached:
                            self._tool_schemas[(server_name, t["name"])] = t.get("inputSchema", {})
                        self._tool_discovery_cache[server_name] = {"tools": cached, "cached_at": now}
                        self._last_discovery_source[server_name] = "disk_cache"
                        return cached
                except Exception as exc:
                    logger.warning(f"Failed to use native MCP discovery: {exc}")

            # 2. Fallback to manual introspection
            for name, obj in inspect.getmembers(module, inspect.isfunction):
                if name.startswith("_"):
                    continue
                
                # Filter for tools: check for common MCP tool markers or specific required names
                is_tool = (
                    getattr(obj, "is_mcp_tool", False) or 
                    hasattr(obj, "_mcp_tool") or
                    name in [
                        "set_allowed_directory", "list_directory", "read_file", "write_file", 
                        "edit_file", "move_file", "create_directory", "delete_file", 
                        "search_files", "grep_search", "get_repo_map", "propose_plan",
                        "list_allowed_directories", "read_media_file_base64", "get_environment_info",
                        "fetch_url", "search_web", "execute_command"
                    ]
                )
                if not is_tool:
                    continue
                
                # Introspect signature
                sig = inspect.signature(obj)
                properties = {}
                required = []
                
                type_map = {
                    str: "string",
                    int: "integer",
                    float: "number",
                    bool: "boolean",
                    list: "array",
                    dict: "object",
                }

                for param_name, param in sig.parameters.items():
                    if param_name == "self":
                        continue
                    
                    param_type = "string" # Default
                    if param.annotation in type_map:
                        param_type = type_map[param.annotation]
                    
                    properties[param_name] = {
                        "type": param_type,
                        "description": f"Parameter: {param_name}"
                    }
                    
                    if param.default is inspect.Parameter.empty:
                        required.append(param_name)

                tools.append(
                    {
                        "name": name,
                        "description": (obj.__doc__ or "").strip(),
                        "inputSchema": {
                            "type": "object",
                            "properties": properties,
                            "required": required,
                        },
                    }
                )
            
            # Update schema lookup for coercion
            for t in tools:
                 self._tool_schemas[(server_name, t["name"])] = t["inputSchema"]

            self._tool_discovery_cache[server_name] = {
                "tools": tools,
                "cached_at": now,
            }
            self._last_discovery_source[server_name] = "fresh"
            # E.3: persist to disk for next-startup fallback
            if tools:
                self._save_disk_tool_cache(server_name, tools)
            return tools

        # Placeholder for future MCP SDK mode
        logger.info(f"Discovering tools from {server_name}")
        tools: List[Dict[str, Any]] = []
        self._tool_discovery_cache[server_name] = {
            "tools": tools,
            "cached_at": now,
        }
        self._last_discovery_source[server_name] = "fresh"
        return tools

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
        # Phase 4.4: Route to external HTTP MCP server if registered
        if server_name in self._external_servers:
            ext = self._external_servers[server_name]
            logger.info("Routing %s.%s to external MCP server %s", server_name, tool_name, ext["url"])
            result = await self._call_external_mcp(
                server_url=ext["url"],
                tool_name=tool_name,
                tool_input=tool_input,
                api_key=ext.get("api_key", ""),
            )
            if isinstance(result, (dict, list)):
                return json.dumps(result, ensure_ascii=False)
            return str(result)

        if server_name not in self._servers:
            raise MCPServerNotInitializedError(f"Server {server_name} not initialized")

        logger.info(f"Executing {server_name}.{tool_name}({tool_input})")

        # Coerce types based on schema
        schema = self._tool_schemas.get((server_name, tool_name))
        if schema and schema.get("type") == "object":
            props = schema.get("properties", {})
            for key, val in list(tool_input.items()):
                if key in props:
                    prop_type = props[key].get("type")
                    if prop_type == "integer" and isinstance(val, str):
                        try: tool_input[key] = int(val)
                        except: pass
                    elif prop_type == "number" and isinstance(val, str):
                        try: tool_input[key] = float(val)
                        except: pass
                    elif prop_type == "boolean" and isinstance(val, str):
                        if val.lower() in ("true", "yes", "1"): tool_input[key] = True
                        elif val.lower() in ("false", "no", "0"): tool_input[key] = False

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
                        json.dumps(
                            {
                                "event": "mcp.tool.retry",
                                "server": server_name,
                                "tool": tool_name,
                                "attempt": attempt,
                                "max_retries": max_retries,
                                "backoff_seconds": backoff,
                                "error_code": "MCP_TOOL_TIMEOUT",
                            },
                            ensure_ascii=True,
                        )
                    )
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    last_error = exc
                    error = self._error_detail_from_exception(exc)
                    if attempt >= max_retries:
                        logger.error(
                            json.dumps(
                                {
                                    "event": "mcp.tool.failed",
                                    "server": server_name,
                                    "tool": tool_name,
                                    "attempt": attempt,
                                    "max_retries": max_retries,
                                    "error_code": error.code,
                                    "error": error.message,
                                },
                                ensure_ascii=True,
                            )
                        )
                        raise MCPToolExecutionError(
                            f"{error.code}: Tool {server_name}.{tool_name} failed: {exc}"
                        ) from exc
                    backoff = 0.1 * attempt
                    logger.warning(
                        json.dumps(
                            {
                                "event": "mcp.tool.retry",
                                "server": server_name,
                                "tool": tool_name,
                                "attempt": attempt,
                                "max_retries": max_retries,
                                "backoff_seconds": backoff,
                                "error_code": error.code,
                                "error": error.message,
                            },
                            ensure_ascii=True,
                        )
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

    async def refresh_tools(
        self,
        tool_registry: 'ToolRegistry',
        *,
        force_refresh: bool = True,
        clear_cache: bool = False,
    ) -> Dict[str, int]:
        """
        Refresh tool discovery from all active MCP servers.
        
        Returns:
            Dict mapping server_name -> count of discovered tools
        """
        if clear_cache:
            self.clear_tool_cache()

        results = {}
        metadata: Dict[str, Dict[str, Any]] = {}
        for server_name in self._servers.keys():
            try:
                tools = await self.discover_tools(server_name, force_refresh=force_refresh)
                tool_registry.register_tools_from_mcp_discovery(server_name, tools)
                results[server_name] = len(tools)
                metadata[server_name] = {
                    "status": "ok",
                    "source": self._last_discovery_source.get(server_name, "unknown"),
                    "tool_count": len(tools),
                    "cache": self.get_discovery_cache_status().get(server_name, {}),
                }
                logger.info(f"Refreshed {len(tools)} tools from {server_name}")
            except Exception as e:
                error = self._error_detail_from_exception(e)
                logger.error(f"Failed to refresh tools from {server_name}: {e}")
                results[server_name] = 0
                metadata[server_name] = {
                    "status": "error",
                    "source": "error",
                    "tool_count": 0,
                    "error": str(e),
                    "error_code": error.code,
                    "retryable": error.retryable,
                    "recommended_fix": self._recommended_fix(error.code),
                }
        self._last_refresh_metadata = metadata
        return results

    def _calculate_backoff_delay(self, server_name: str) -> float:
        """Calculate exponential backoff delay for a server."""
        attempts = self._server_failures.get(server_name, 0)
        if attempts >= self.MAX_RETRY_ATTEMPTS:
            return self.MAX_BACKOFF_SECONDS
        delay = self.INITIAL_BACKOFF_SECONDS * (2 ** attempts)
        return min(delay, self.MAX_BACKOFF_SECONDS)

    async def reconnect_server(self, server_name: str) -> MCPReconnectResult:
        """
        Attempt to reconnect to a failed MCP server with exponential backoff.
        
        Returns:
            Structured reconnect result.
        """
        now = time.time()

        if server_name not in self._server_configs:
            logger.error(f"Server {server_name} not in configs")
            return MCPReconnectResult(
                status="unknown_server",
                success=False,
                error_code="MCP_SERVER_UNKNOWN",
                reason="Server not found in orchestrator configuration",
                retryable=False,
                attempts_used=0,
                attempts_remaining=0,
                recommended_fix="Verify server name in MCP config",
            )

        existing = self._servers.get(server_name)
        if existing and existing.get("status") == "initialized":
            attempts = self._server_failures.get(server_name, 0)
            return MCPReconnectResult(
                status="already_initialized",
                success=True,
                attempts_used=attempts,
                attempts_remaining=max(0, self.MAX_RETRY_ATTEMPTS - attempts),
            )

        attempts = self._server_failures.get(server_name, 0)
        if attempts >= self.MAX_RETRY_ATTEMPTS:
            logger.error(f"Server {server_name} exceeded max retry attempts ({self.MAX_RETRY_ATTEMPTS})")
            return MCPReconnectResult(
                status="max_attempts_exceeded",
                success=False,
                error_code="MCP_RECONNECT_MAX_ATTEMPTS_EXCEEDED",
                reason="Maximum reconnect attempts exceeded",
                retryable=False,
                attempts_used=attempts,
                attempts_remaining=0,
                recommended_fix="Inspect startup summary and fix server configuration before retrying",
            )

        last_retry = self._server_last_retry.get(server_name, 0.0)
        backoff_delay = self._calculate_backoff_delay(server_name)
        retry_ready_at = last_retry + backoff_delay
        if last_retry > 0 and now < retry_ready_at:
            wait_seconds = max(0.0, retry_ready_at - now)
            return MCPReconnectResult(
                status="backoff_active",
                success=False,
                error_code="MCP_RECONNECT_BACKOFF_ACTIVE",
                reason="Reconnect is temporarily delayed by backoff policy",
                retryable=True,
                attempts_used=attempts,
                attempts_remaining=max(0, self.MAX_RETRY_ATTEMPTS - attempts),
                next_retry_after_seconds=round(wait_seconds, 3),
                recommended_fix="Wait for backoff window and retry",
            )

        try:
            config = self._server_configs[server_name]
            await self.initialize_server(config)
            self._server_failures[server_name] = 0  # Reset on success
            self._server_last_retry[server_name] = now
            logger.info(f"Successfully reconnected to server {server_name}")
            return MCPReconnectResult(
                status="reconnected",
                success=True,
                attempts_used=attempts,
                attempts_remaining=self.MAX_RETRY_ATTEMPTS,
            )
        except Exception as e:
            attempts_after = attempts + 1
            self._server_failures[server_name] = attempts_after
            self._server_last_retry[server_name] = now
            error = self._error_detail_from_exception(e)
            logger.error(
                "Reconnection attempt %s for %s failed [%s]: %s",
                attempts_after,
                server_name,
                error.code,
                e,
            )
            return MCPReconnectResult(
                status="failed",
                success=False,
                error_code=error.code,
                reason=error.message,
                retryable=error.retryable,
                attempts_used=attempts_after,
                attempts_remaining=max(0, self.MAX_RETRY_ATTEMPTS - attempts_after),
                next_retry_after_seconds=round(self._calculate_backoff_delay(server_name), 3),
                recommended_fix=self._recommended_fix(error.code),
            )

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

    # ── Phase 4.3: MCP Proxy Mode ─────────────────────────────────────────────

    def get_proxy_tool_schema(self) -> Dict[str, Any]:
        """Return a single catch-all mcp_proxy tool schema for proxy mode."""
        return {
            "type": "function",
            "function": {
                "name": "mcp_proxy",
                "description": "Execute any MCP tool. Use this to call filesystem, search, or shell tools.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "server": {
                            "type": "string",
                            "description": "MCP server name (e.g. 'local-mcp')",
                        },
                        "tool": {
                            "type": "string",
                            "description": "Tool name to call",
                        },
                        "args": {
                            "type": "object",
                            "description": "Tool arguments as key-value pairs",
                        },
                    },
                    "required": ["tool", "args"],
                },
            },
        }

    async def execute_proxy_call(
        self,
        proxy_input: Dict[str, Any],
        timeout_seconds: int = 10,
        max_retries: int = 2,
    ) -> Any:
        """Dispatch an mcp_proxy tool call to the appropriate server."""
        server = proxy_input.get("server", "local-mcp")
        tool = proxy_input.get("tool", "")
        args = proxy_input.get("args", {})
        return await self.execute_tool(
            server_name=server,
            tool_name=tool,
            tool_input=args,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )

    # ── Phase 4.4: External MCP Servers ──────────────────────────────────────

    def register_external_server(self, name: str, url: str, api_key: str = "") -> None:
        """Register an external HTTP-based MCP server."""
        self._external_servers[name] = {"url": url.rstrip("/"), "api_key": api_key}
        logger.info("Registered external MCP server: %s -> %s", name, url)

    def register_external_servers_from_config(self, server_urls: list[str]) -> None:
        """
        Parse and register external MCP servers from a list of URL strings.

        Each URL may include query params for auth:
          http://host:port?api_key=KEY  or  http://host:port?bearer=TOKEN
        """
        from urllib.parse import urlparse, parse_qs, urlunparse

        for raw_url in server_urls:
            try:
                parsed = urlparse(raw_url)
                params = parse_qs(parsed.query)
                api_key = ""
                if "api_key" in params:
                    api_key = params["api_key"][0]
                elif "bearer" in params:
                    api_key = params["bearer"][0]
                # Strip auth query params from the base URL
                clean = urlunparse(parsed._replace(query=""))
                # Derive a server name from the netloc
                server_name = parsed.netloc.replace(":", "_").replace(".", "-")
                self.register_external_server(server_name, clean, api_key)
            except Exception as exc:
                logger.warning("Failed to register external MCP server %s: %s", raw_url, exc)

    async def _call_external_mcp(
        self,
        server_url: str,
        tool_name: str,
        tool_input: Dict[str, Any],
        api_key: str = "",
    ) -> Any:
        """Call an external MCP server via HTTP POST /tools/{tool_name}."""
        try:
            import aiohttp  # type: ignore[import]
        except ImportError:
            logger.warning(
                "aiohttp is not installed — cannot call external MCP server %s. "
                "Install with: pip install aiohttp",
                server_url,
            )
            return {"error": "aiohttp not available"}

        headers: Dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{server_url}/tools/{tool_name}",
                json=tool_input,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                return await resp.json()

    def __repr__(self) -> str:
        return f"MCPOrchestrator({len(self._servers)} servers)"
