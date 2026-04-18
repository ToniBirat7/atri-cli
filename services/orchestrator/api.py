"""
FastAPI server for orchestrator service.

Exposes orchestrator as HTTP API:
- POST /chat — Execute agent loop (user message → LLM → tools → response)
- GET /health — Health check
- GET /tools — List available tools

Phase 1: Basic API for chat and health checks.
Phase 2: Streaming responses via Server-Sent Events.
Phase 7: Full observability with request/response logging and tracing.
"""

from collections import defaultdict, deque
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import logging
import json
import uuid
import time
from pathlib import Path
import asyncio

try:
    from .config import OrchestratorConfig
    from .database import OrchestratorDatabase
    from .auth import AuthContext, JwtAuth, RequestAuthenticator
    from .redis_rate_limit import DistributedRateLimiter
    from .tracing import instrument_fastapi, setup_tracing
    from .llm_adapter import LLMAdapter
    from .mcp_orchestrator import MCPOrchestrator, MCPServerConfig
    from .prompt_policy import build_system_prompt, normalize_prompt_profile
    from .tool_registry import ToolRegistry
    from .agent_loop import AgentLoop
    from .permissions import evaluate_permission
    from .logging_context import set_request_id, get_request_id
except ImportError:
    # Fallback for `uvicorn api:app` when running from services/orchestrator.
    from config import OrchestratorConfig
    from database import OrchestratorDatabase
    from auth import AuthContext, JwtAuth, RequestAuthenticator
    from redis_rate_limit import DistributedRateLimiter
    from tracing import instrument_fastapi, setup_tracing
    from llm_adapter import LLMAdapter
    from mcp_orchestrator import MCPOrchestrator, MCPServerConfig
    from prompt_policy import build_system_prompt, normalize_prompt_profile
    from tool_registry import ToolRegistry
    from agent_loop import AgentLoop
    from permissions import evaluate_permission
    from logging_context import set_request_id, get_request_id

logger = logging.getLogger(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)

_resolved_api_path = Path(__file__).resolve()
DEFAULT_ALLOWED_DIRECTORY = str(_resolved_api_path.parents[2] if len(_resolved_api_path.parents) > 2 else _resolved_api_path.parent)


def _log_event(event: str, **fields: Any) -> None:
    payload: Dict[str, Any] = {
        "event": event,
        "request_id": get_request_id(),
    }
    payload.update(fields)
    logger.info(json.dumps(payload, ensure_ascii=True))


class ChatRequest(BaseModel):
    """Request to execute agent loop."""
    message: str = Field(..., description="User message")
    conversation_id: Optional[str] = Field(None, description="Conversation ID for multi-turn")
    max_turns: Optional[int] = Field(None, description="Override max turns")
    allowed_directory: Optional[str] = Field(
        None,
        description="User-selected filesystem root for MCP tools",
    )
    prompt_profile: Optional[str] = Field(
        None,
        description="Prompt profile to use for this request; requires admin authentication",
    )


class ChatResponse(BaseModel):
    """Response from agent loop execution."""
    response: str = Field(..., description="Final response from agent")
    conversation_id: str = Field(..., description="Conversation ID")
    turns: int = Field(..., description="Number of agent loop turns")
    tool_calls: int = Field(..., description="Total tool calls executed")
    model: str = Field(..., description="LLM model used")
    request_id: str = Field(..., description="Request correlation ID")


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(..., description="Service status")
    llm_connected: bool = Field(..., description="LLM endpoint reachable")
    mcp_servers: Dict[str, Dict[str, Any]] = Field(..., description="MCP server statuses")


class ToolInfo(BaseModel):
    """Information about a tool."""
    name: str
    description: str
    server: str
    category: Optional[str] = None


class ToolsResponse(BaseModel):
    """Response with available tools."""
    tools: List[ToolInfo]
    total: int


class MetricsResponse(BaseModel):
    """Runtime metrics for the orchestrator."""
    uptime_seconds: float
    chat_requests_total: int
    chat_requests_succeeded: int
    chat_requests_failed: int
    total_tool_calls: int
    active_mcp_servers: int
    allowed_directory_custom: int
    allowed_directory_default: int


class ValidateDirectoryRequest(BaseModel):
    """Request to validate a directory path."""
    path: str = Field(..., description="Directory path to validate")


class ValidateDirectoryResponse(BaseModel):
    """Response from directory validation."""
    ok: bool = Field(..., description="Whether the directory is valid and accessible")
    path: str = Field(..., description="The validated path")
    error: Optional[str] = Field(None, description="Error message if validation failed")
    message: Optional[str] = Field(None, description="Human-readable status message")


class ConversationSummary(BaseModel):
    conversation_id: str
    prompt_profile: str
    created_at: str
    updated_at: str


class ConversationTurnSummary(BaseModel):
    turn_index: int
    user_message: str
    assistant_response: str
    status: str
    total_tool_calls: int
    model: str
    created_at: str


class ConversationDetailResponse(BaseModel):
    conversation: ConversationSummary
    turns: List[ConversationTurnSummary]


class ConversationResumeResponse(BaseModel):
    conversation_id: str
    prompt_profile: str
    turn_count: int


class ConversationForkRequest(BaseModel):
    new_conversation_id: Optional[str] = Field(
        None,
        description="Optional explicit conversation id for the fork; generated if omitted",
    )


class ConversationForkResponse(BaseModel):
    source_conversation_id: str
    new_conversation_id: str


class PermissionsEvaluateRequest(BaseModel):
    tool_call: str = Field(..., description="Tool call expression, e.g. Bash(git status)")
    mode: str = Field(default="default", description="Permission mode")
    allow: List[str] = Field(default_factory=list)
    ask: List[str] = Field(default_factory=list)
    deny: List[str] = Field(default_factory=list)


class PermissionsEvaluateResponse(BaseModel):
    action: str
    reason: str


class ConversationsResponse(BaseModel):
    conversations: List[ConversationSummary]
    total: int


# Global state (Phase 1)
# In production (Phase 9), move to database/session management
app = FastAPI(
    title="Tarbar_AI Orchestrator",
    version="0.1.0",
    description="Orchestrates LLM + MCP for local agentic AI",
)

config: Optional[OrchestratorConfig] = None
llm_adapter: Optional[LLMAdapter] = None
mcp_orchestrator: Optional[MCPOrchestrator] = None
tool_registry: Optional[ToolRegistry] = None
agent_loop: Optional[AgentLoop] = None
conversation_store: Optional[OrchestratorDatabase] = None
request_authenticator: Optional[RequestAuthenticator] = None
rate_limiter: Optional[DistributedRateLimiter] = None
service_started_at = time.monotonic()
chat_requests_total = 0
chat_requests_succeeded = 0
chat_requests_failed = 0
total_tool_calls = 0
# Telemetry for allowed_directory feature
allowed_directory_requests_with_custom = 0
allowed_directory_requests_with_default = 0
allowed_directory_validation_passed = 0
allowed_directory_validation_failed = 0
rate_limit_windows: Dict[str, deque[float]] = defaultdict(deque)
rate_limit_lock = __import__("asyncio").Lock()


def _extract_client_ip(http_request: Request) -> str:
    if http_request.client and http_request.client.host:
        return http_request.client.host
    return "unknown"


def _extract_api_key(http_request: Request) -> Optional[str]:
    authorization = http_request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization.split(None, 1)[1].strip()
        return token or None

    header_key = http_request.headers.get("x-api-key")
    if header_key:
        return header_key.strip() or None

    return None


def _anonymous_auth_context() -> AuthContext:
    return AuthContext(
        subject="anonymous",
        issuer="local",
        audience="orchestrator",
        scopes=["chat:read", "chat:write"],
        is_admin=False,
    )


def _authenticate_request(http_request: Request) -> AuthContext:
    if config is None:
        return _anonymous_auth_context()

    auth_config = getattr(config, "auth", None)
    security_config = getattr(config, "security", None)
    jwt_secret = getattr(auth_config, "jwt_secret", None)
    api_key = getattr(security_config, "api_key", None)
    admin_api_key = getattr(security_config, "admin_api_key", None)

    auth_material_enabled = bool(jwt_secret or api_key or admin_api_key)
    if not auth_material_enabled:
        return _anonymous_auth_context()

    if request_authenticator is not None:
        return request_authenticator.authenticate(http_request)

    token = _extract_api_key(http_request)
    if token and token in {api_key, admin_api_key}:
        return AuthContext(
            subject="api-key-client",
            issuer="legacy",
            audience="orchestrator",
            scopes=["chat:read", "chat:write"],
            is_admin=token == admin_api_key,
        )

    if jwt_secret and token:
        try:
            return JwtAuth(
                jwt_secret,
                issuer=getattr(auth_config, "jwt_issuer", "tarbar-ai"),
                audience=getattr(auth_config, "jwt_audience", "tarbar-ai-orchestrator"),
            ).verify(token)
        except Exception as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    if auth_material_enabled:
        raise HTTPException(status_code=401, detail="Unauthorized")

    return _anonymous_auth_context()


def _require_api_key(http_request: Request) -> None:
    _authenticate_request(http_request)


def _build_request_system_prompt(request: ChatRequest, is_admin: bool) -> tuple[str, str]:
    if config is None:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")

    selected_profile = config.prompt_policy.default_profile
    if request.prompt_profile:
        if not is_admin:
            raise HTTPException(status_code=403, detail="Prompt profile override requires admin authentication")
        selected_profile = request.prompt_profile

    try:
        normalized_profile = normalize_prompt_profile(selected_profile)
        system_prompt = build_system_prompt(
            normalized_profile,
            assistant_name="Tarbar_AI",
            model_name=config.llm.model,
            enable_thinking=config.agent_loop.enable_thinking,
            fallback_text=config.prompt_policy.fallback_text,
            disclaimer_text=config.prompt_policy.disclaimer_text,
            legal_help_line=config.prompt_policy.legal_help_line,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return normalized_profile, system_prompt


def _resolve_conversation_id(request: ChatRequest) -> str:
    return request.conversation_id or f"conv_{uuid.uuid4().hex[:12]}"


def _serialize_turn_history(state: Any) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for turn in getattr(state, "turns_history", []):
        history.append(
            {
                "turn_number": turn.turn_number,
                "user_input": turn.user_input,
                "llm_response": turn.llm_response,
                "tool_calls_requested": turn.tool_calls_requested,
                "tool_calls_executed": turn.tool_calls_executed,
                "outcome": turn.outcome.value if getattr(turn, "outcome", None) else None,
                "error": turn.error,
                "metadata": turn.metadata,
            }
        )
    return history


async def _enforce_rate_limit(http_request: Request) -> None:
    if config is None or config.security.rate_limit_per_minute <= 0:
        return

    client_key = f"{_extract_client_ip(http_request)}:{http_request.url.path}"

    if rate_limiter is not None:
        await rate_limiter.enforce(client_key)
        return

    now = time.monotonic()
    window_start = now - 60.0

    async with rate_limit_lock:
        bucket = rate_limit_windows[client_key]
        while bucket and bucket[0] < window_start:
            bucket.popleft()

        if len(bucket) >= config.security.rate_limit_per_minute:
            retry_after = max(1, int(60 - (now - bucket[0])))
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )

        bucket.append(now)


def _chunk_text(text: str, chunk_size: int = 96) -> List[str]:
    if not text:
        return []
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


async def _run_agent_request(
    request: ChatRequest,
    request_id: str,
    conversation_id: str,
    prompt_profile: str,
    *,
    system_prompt: Optional[str] = None,
    event_callback: Optional[Any] = None,
) -> ChatResponse:
    global chat_requests_succeeded, chat_requests_failed, total_tool_calls
    global allowed_directory_requests_with_custom, allowed_directory_requests_with_default

    if (
        agent_loop is None
        or llm_adapter is None
        or mcp_orchestrator is None
        or tool_registry is None
        or config is None
    ):
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")

    if conversation_store is not None:
        await conversation_store.ensure_conversation(conversation_id, prompt_profile)

    original_max_turns = agent_loop.max_turns
    try:
        _log_event(
            "chat.request.received",
            conversation_id=request.conversation_id or "default",
            message_preview=request.message[:80],
            requested_max_turns=request.max_turns,
            user_allowed_directory=request.allowed_directory,
        )

        if request.max_turns:
            agent_loop.max_turns = request.max_turns

        prior_messages: list[dict[str, str]] = []
        if conversation_store is not None and request.conversation_id:
            prior_messages = await conversation_store.build_chat_history_messages(
                conversation_id=request.conversation_id,
                max_turns=10,
            )

        selected_allowed_directory = request.allowed_directory or DEFAULT_ALLOWED_DIRECTORY
        selected_server = "local-mcp"
        selected_tool = "set_allowed_directory"
        if hasattr(tool_registry, "resolve_tool_call"):
            try:
                selected_server, selected_tool = tool_registry.resolve_tool_call("set_allowed_directory")
            except Exception:
                pass

        await mcp_orchestrator.execute_tool(
            server_name=selected_server,
            tool_name=selected_tool,
            tool_input={"path": selected_allowed_directory},
        )
        _log_event(
            "chat.allowed_directory.set",
            selected_allowed_directory=selected_allowed_directory,
            used_default=(request.allowed_directory is None),
        )

        # Track allowed_directory telemetry
        if request.allowed_directory:
            allowed_directory_requests_with_custom += 1
        else:
            allowed_directory_requests_with_default += 1

        try:
            response, state = await agent_loop.run(
                user_message=request.message,
                llm_adapter=llm_adapter,
                mcp_orchestrator=mcp_orchestrator,
                tool_registry=tool_registry,
                system_prompt=system_prompt,
                prior_messages=prior_messages,
                event_callback=event_callback,
            )
        except TypeError:
            # Compatibility fallback for older loop implementations in tests.
            response, state = await agent_loop.run(
                user_message=request.message,
                llm_adapter=llm_adapter,
                mcp_orchestrator=mcp_orchestrator,
                tool_registry=tool_registry,
                system_prompt=system_prompt,
            )

        if conversation_store is not None:
            tool_events: list[dict[str, Any]] = []
            for turn in getattr(state, "turns_history", []):
                tool_events.extend(turn.metadata.get("tool_events", []))

            await conversation_store.record_turn(
                conversation_id=conversation_id,
                request_id=request_id,
                turn_index=state.turn,
                user_message=request.message,
                assistant_response=response,
                status=state.status,
                total_tool_calls=state.total_tool_calls,
                model=config.llm.model,
                system_prompt=system_prompt,
                turn_history=_serialize_turn_history(state),
                tool_events=tool_events,
            )

        _log_event(
            "chat.request.completed",
            conversation_id=conversation_id,
            turns=state.turn,
            tool_calls=state.total_tool_calls,
            status=state.status,
        )

        chat_requests_succeeded += 1
        total_tool_calls += state.total_tool_calls

        return ChatResponse(
            response=response,
            conversation_id=conversation_id,
            turns=state.turn,
            tool_calls=state.total_tool_calls,
            model=config.llm.model,
            request_id=request_id,
        )
    except asyncio.CancelledError:
        chat_requests_failed += 1
        raise
    except Exception as e:
        chat_requests_failed += 1
        logger.error(
            json.dumps(
                {
                    "event": "chat.request.failed",
                    "request_id": request_id,
                    "error": str(e),
                },
                ensure_ascii=True,
            )
        )
        raise HTTPException(status_code=500, detail=f"Agent execution failed: {str(e)}")
    finally:
        agent_loop.max_turns = original_max_turns


@app.on_event("startup")
async def startup():
    """Initialize orchestrator on server startup."""
    global config, llm_adapter, mcp_orchestrator, tool_registry, agent_loop, conversation_store, request_authenticator, rate_limiter
    
    _log_event("orchestrator.startup.begin")
    
    config = OrchestratorConfig.from_env()
    conversation_store = OrchestratorDatabase(
        config.database.url,
        enabled=config.database.enable_persistence,
    )
    await conversation_store.initialize()
    request_authenticator = RequestAuthenticator(
        jwt_auth=JwtAuth(
            config.auth.jwt_secret,
            issuer=config.auth.jwt_issuer,
            audience=config.auth.jwt_audience,
        ),
        api_key=config.security.api_key,
        admin_api_key=config.security.admin_api_key,
        mode=config.auth.mode,
    )
    rate_limiter = DistributedRateLimiter(
        redis_url=config.redis.url if config.redis.enabled else None,
        limit_per_minute=config.security.rate_limit_per_minute,
    )
    await rate_limiter.initialize()
    setup_tracing(
        service_name="tarbar-orchestrator",
        otlp_endpoint=config.telemetry.otlp_endpoint,
        enabled=config.telemetry.enabled,
    )
    llm_adapter = LLMAdapter(config.llm)
    mcp_orchestrator = MCPOrchestrator()
    tool_registry = ToolRegistry()
    agent_loop = AgentLoop(
        max_turns=config.agent_loop.max_turns,
        max_tool_calls_per_turn=config.agent_loop.max_tool_calls_per_turn,
        enable_tool_use=config.agent_loop.enable_tool_use,
        enable_thinking=config.agent_loop.enable_thinking,
        tool_timeout_seconds=config.mcp.tool_timeout_seconds,
        max_tool_call_retries=config.mcp.max_tool_call_retries,
    )
    
    # Initialize MCP servers (single default or configured multi-server set).
    try:
        configured_servers = config.mcp.servers or [
            {
                "name": "local-mcp",
                "command": "fastmcp run services/mcp/main.py:mcp",
                "transport": config.mcp.default_transport,
            }
        ]

        for server_entry in configured_servers:
            server_name = server_entry.get("name")
            command = server_entry.get("command")
            if not server_name or not command:
                logger.warning(
                    json.dumps(
                        {
                            "event": "mcp.server.invalid_config",
                            "config": server_entry,
                        },
                        ensure_ascii=True,
                    )
                )
                continue

            mcp_config = MCPServerConfig(
                name=server_name,
                command=command,
                transport=server_entry.get("transport", config.mcp.default_transport),
            )
            await mcp_orchestrator.initialize_server(mcp_config)
            discovered_tools = await mcp_orchestrator.discover_tools(server_name)
            tool_registry.register_tools_from_mcp_discovery(server_name, discovered_tools)
            _log_event("mcp.tools.registered", tool_count=len(discovered_tools), server=server_name)
            _log_event("mcp.server.initialized", server=server_name)
    except Exception as e:
        logger.warning(json.dumps({"event": "mcp.server.init_failed", "error": str(e)}, ensure_ascii=True))
    
    _log_event("orchestrator.startup.complete")


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on server shutdown."""
    global llm_adapter, mcp_orchestrator, rate_limiter
    
    _log_event("orchestrator.shutdown.begin")
    
    if mcp_orchestrator:
        await mcp_orchestrator.shutdown_all()
    
    if llm_adapter:
        await llm_adapter.close()

    if rate_limiter:
        await rate_limiter.close()
    
    _log_event("orchestrator.shutdown.complete")


instrument_fastapi(app)


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, http_request: Request) -> ChatResponse:
    """
    Execute agent loop for a user message.
    
    Returns the final response after tool use if applicable.
    """
    if (
        agent_loop is None
        or llm_adapter is None
        or mcp_orchestrator is None
        or tool_registry is None
    ):
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")

    await _enforce_rate_limit(http_request)
    _require_api_key(http_request)
    auth_context = _authenticate_request(http_request)
    
    global chat_requests_total, chat_requests_succeeded, chat_requests_failed, total_tool_calls

    request_id = uuid.uuid4().hex[:12]
    conversation_id = _resolve_conversation_id(request)
    set_request_id(request_id)
    chat_requests_total += 1

    try:
        selected_profile, system_prompt = _build_request_system_prompt(request, auth_context.is_admin)
        _log_event("chat.prompt_profile.selected", profile=selected_profile)
        return await _run_agent_request(
            request,
            request_id,
            conversation_id,
            selected_profile,
            system_prompt=system_prompt,
        )
    finally:
        set_request_id(None)


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest, http_request: Request) -> StreamingResponse:
    """Execute chat request and stream the final response as SSE chunks."""
    if (
        agent_loop is None
        or llm_adapter is None
        or mcp_orchestrator is None
        or tool_registry is None
    ):
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")

    await _enforce_rate_limit(http_request)
    _require_api_key(http_request)
    auth_context = _authenticate_request(http_request)

    global chat_requests_total
    chat_requests_total += 1

    request_id = uuid.uuid4().hex[:12]
    conversation_id = _resolve_conversation_id(request)

    async def event_stream():
        set_request_id(request_id)
        progress_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        async def _on_progress(event: dict[str, Any]) -> None:
            await progress_queue.put(event)

        async def _run_with_progress() -> ChatResponse:
            selected_profile, system_prompt = _build_request_system_prompt(request, auth_context.is_admin)
            _log_event("chat.prompt_profile.selected", profile=selected_profile)
            return await _run_agent_request(
                request,
                request_id,
                conversation_id,
                selected_profile,
                system_prompt=system_prompt,
                event_callback=_on_progress,
            )

        try:
            yield f"data: {json.dumps({'request_id': request_id})}\n\n"
            yield f"data: {json.dumps({'conversation_id': conversation_id})}\n\n"

            run_task = asyncio.create_task(_run_with_progress())
            while not run_task.done():
                try:
                    event = await asyncio.wait_for(progress_queue.get(), timeout=0.15)
                    yield f"data: {json.dumps({'event': event}, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    continue

            while not progress_queue.empty():
                event = progress_queue.get_nowait()
                yield f"data: {json.dumps({'event': event}, ensure_ascii=False)}\n\n"

            result = await run_task
            for chunk in _chunk_text(result.response):
                yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except HTTPException as e:
            yield f"data: {json.dumps({'error': str(e.detail)})}\n\n"
            yield "data: [DONE]\n\n"
        except asyncio.CancelledError:
            return
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            set_request_id(None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check endpoint."""
    llm_connected = False
    
    if llm_adapter:
        try:
            # Quick test of LLM connection
            await llm_adapter.client.get("/models")
            llm_connected = True
        except Exception as e:
            logger.warning(f"LLM health check failed: {e}")
    
    mcp_status = {}
    if mcp_orchestrator:
        mcp_status = mcp_orchestrator.get_server_status()
    
    return HealthResponse(
        status="healthy" if llm_connected else "degraded",
        llm_connected=llm_connected,
        mcp_servers=mcp_status,
    )


@app.get("/live")
async def live() -> Dict[str, str]:
    """Liveness probe endpoint for container/platform health checks."""
    return {"status": "alive"}


@app.get("/ready")
async def ready() -> Dict[str, str]:
    """Readiness probe endpoint for deployment rollouts."""
    if config is None or llm_adapter is None or mcp_orchestrator is None or tool_registry is None:
        raise HTTPException(status_code=503, detail="orchestrator_not_initialized")
    return {"status": "ready"}


@app.get("/tools", response_model=ToolsResponse)
async def list_tools(http_request: Request) -> ToolsResponse:
    """List available tools."""
    if tool_registry is None:
        raise HTTPException(status_code=500, detail="Tool registry not initialized")

    await _enforce_rate_limit(http_request)
    _require_api_key(http_request)
    _authenticate_request(http_request)
    
    tools = tool_registry.list_all_tools()
    _log_event("tools.listed", total=len(tools))
    
    return ToolsResponse(
        tools=[
            ToolInfo(
                name=tool.name,
                description=tool.description,
                server=tool.server_name,
                category=tool.category,
            )
            for tool in tools
        ],
        total=len(tools),
    )


@app.post("/validate-directory", response_model=ValidateDirectoryResponse)
async def validate_directory(req: ValidateDirectoryRequest, http_request: Request) -> ValidateDirectoryResponse:
    """
    Validate that a directory path exists and is accessible by the MCP server.
    
    Used by frontend to verify directory selection before sending to orchestrator.
    """
    await _enforce_rate_limit(http_request)
    _authenticate_request(http_request)
    
    if not req.path or not req.path.strip():
        return ValidateDirectoryResponse(
            ok=False,
            path="",
            error="Path cannot be empty",
            message="Please provide a directory path.",
        )
    
    try:
        path = Path(req.path).expanduser().resolve()
        
        if not path.exists():
            return ValidateDirectoryResponse(
                ok=False,
                path=req.path,
                error="Path does not exist",
                message=f"Directory not found: {req.path}",
            )
        
        if not path.is_dir():
            return ValidateDirectoryResponse(
                ok=False,
                path=req.path,
                error="Path is not a directory",
                message=f"Path exists but is not a directory: {req.path}",
            )
        
        # Verify path is readable
        try:
            list(path.iterdir())
        except PermissionError:
            return ValidateDirectoryResponse(
                ok=False,
                path=req.path,
                error="Permission denied",
                message=f"No permission to access: {req.path}",
            )
        
        _log_event(
            "directory.validated",
            path=str(path),
            status="ok",
        )
        
        return ValidateDirectoryResponse(
            ok=True,
            path=str(path),
            message=f"Directory is valid and accessible: {path.name or path}",
        )
    
    except Exception as exc:
        _log_event(
            "directory.validation.failed",
            path=req.path,
            error=str(exc),
        )
        return ValidateDirectoryResponse(
            ok=False,
            path=req.path,
            error=f"Validation error: {str(exc)}",
            message="Failed to validate directory path.",
        )


@app.get("/conversations", response_model=ConversationsResponse)
async def list_conversations(http_request: Request) -> ConversationsResponse:
    if conversation_store is None:
        raise HTTPException(status_code=500, detail="Conversation store not initialized")

    await _enforce_rate_limit(http_request)
    auth_context = _authenticate_request(http_request)
    if config is not None and (config.security.api_key or config.security.admin_api_key or config.auth.jwt_secret):
        if not auth_context.is_admin:
            raise HTTPException(status_code=403, detail="Admin privileges required")

    conversations = await conversation_store.list_conversations()
    return ConversationsResponse(
        conversations=[
            ConversationSummary(
                conversation_id=item.conversation_id,
                prompt_profile=item.prompt_profile,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in conversations
        ],
        total=len(conversations),
    )


@app.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(conversation_id: str, http_request: Request) -> ConversationDetailResponse:
    if conversation_store is None:
        raise HTTPException(status_code=500, detail="Conversation store not initialized")

    await _enforce_rate_limit(http_request)
    auth_context = _authenticate_request(http_request)
    if config is not None and (config.security.api_key or config.security.admin_api_key or config.auth.jwt_secret):
        if not auth_context.is_admin:
            raise HTTPException(status_code=403, detail="Admin privileges required")

    conversation = await conversation_store.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    turns = await conversation_store.list_turns(conversation_id=conversation_id, limit=500)
    return ConversationDetailResponse(
        conversation=ConversationSummary(
            conversation_id=conversation.conversation_id,
            prompt_profile=conversation.prompt_profile,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        ),
        turns=[
            ConversationTurnSummary(
                turn_index=turn.turn_index,
                user_message=turn.user_message,
                assistant_response=turn.assistant_response,
                status=turn.status,
                total_tool_calls=turn.total_tool_calls,
                model=turn.model,
                created_at=turn.created_at,
            )
            for turn in turns
        ],
    )


@app.post("/conversations/{conversation_id}/resume", response_model=ConversationResumeResponse)
async def resume_conversation(conversation_id: str, http_request: Request) -> ConversationResumeResponse:
    if conversation_store is None:
        raise HTTPException(status_code=500, detail="Conversation store not initialized")

    await _enforce_rate_limit(http_request)
    auth_context = _authenticate_request(http_request)
    if config is not None and (config.security.api_key or config.security.admin_api_key or config.auth.jwt_secret):
        if not auth_context.is_admin:
            raise HTTPException(status_code=403, detail="Admin privileges required")

    conversation = await conversation_store.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    turns = await conversation_store.list_turns(conversation_id=conversation_id, limit=1_000)
    return ConversationResumeResponse(
        conversation_id=conversation.conversation_id,
        prompt_profile=conversation.prompt_profile,
        turn_count=len(turns),
    )


@app.post("/conversations/{conversation_id}/fork", response_model=ConversationForkResponse)
async def fork_conversation(
    conversation_id: str,
    request: ConversationForkRequest,
    http_request: Request,
) -> ConversationForkResponse:
    if conversation_store is None:
        raise HTTPException(status_code=500, detail="Conversation store not initialized")

    await _enforce_rate_limit(http_request)
    auth_context = _authenticate_request(http_request)
    if config is not None and (config.security.api_key or config.security.admin_api_key or config.auth.jwt_secret):
        if not auth_context.is_admin:
            raise HTTPException(status_code=403, detail="Admin privileges required")

    new_conversation_id = request.new_conversation_id or f"conv_{uuid.uuid4().hex[:12]}"
    if new_conversation_id == conversation_id:
        raise HTTPException(status_code=400, detail="Fork id must be different from source conversation id")

    created = await conversation_store.fork_conversation(
        source_conversation_id=conversation_id,
        target_conversation_id=new_conversation_id,
    )
    if not created:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return ConversationForkResponse(
        source_conversation_id=conversation_id,
        new_conversation_id=new_conversation_id,
    )


@app.get("/metrics", response_model=MetricsResponse)
async def metrics(http_request: Request) -> MetricsResponse:
    """Runtime metrics for the orchestrator."""
    await _enforce_rate_limit(http_request)
    _require_api_key(http_request)
    _authenticate_request(http_request)

    return MetricsResponse(
        uptime_seconds=round(time.monotonic() - service_started_at, 3),
        chat_requests_total=chat_requests_total,
        chat_requests_succeeded=chat_requests_succeeded,
        chat_requests_failed=chat_requests_failed,
        total_tool_calls=total_tool_calls,
        active_mcp_servers=len(mcp_orchestrator.get_server_status()) if mcp_orchestrator else 0,
        allowed_directory_custom=allowed_directory_requests_with_custom,
        allowed_directory_default=allowed_directory_requests_with_default,
    )


@app.post("/permissions/evaluate", response_model=PermissionsEvaluateResponse)
async def permissions_evaluate(
    request: PermissionsEvaluateRequest,
    http_request: Request,
) -> PermissionsEvaluateResponse:
    await _enforce_rate_limit(http_request)
    _authenticate_request(http_request)

    decision = evaluate_permission(
        tool_call=request.tool_call,
        mode=request.mode,
        allow_rules=request.allow,
        ask_rules=request.ask,
        deny_rules=request.deny,
    )

    return PermissionsEvaluateResponse(action=decision.action, reason=decision.reason)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Tarbar_AI Orchestrator",
        "version": "0.1.0",
        "endpoints": [
            "POST /chat — Execute agent loop",
            "POST /chat/stream — Stream chat response",
            "GET /health — Health check",
            "GET /live — Liveness probe",
            "GET /ready — Readiness probe",
            "GET /tools — List available tools",
            "GET /conversations — List stored conversations",
            "GET /conversations/{id} — Conversation details",
            "POST /conversations/{id}/resume — Validate resumable conversation",
            "POST /conversations/{id}/fork — Create conversation fork",
            "POST /permissions/evaluate — Evaluate permission decision",
            "GET /metrics — Runtime metrics",
        ]
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8001,
        log_level="info",
    )
