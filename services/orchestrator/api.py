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

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import logging
import asyncio

from .config import OrchestratorConfig
from .llm_adapter import LLMAdapter
from .mcp_orchestrator import MCPOrchestrator, MCPServerConfig
from .tool_registry import ToolRegistry
from .agent_loop import AgentLoop

logger = logging.getLogger(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)


class ChatRequest(BaseModel):
    """Request to execute agent loop."""
    message: str = Field(..., description="User message")
    conversation_id: Optional[str] = Field(None, description="Conversation ID for multi-turn")
    max_turns: Optional[int] = Field(None, description="Override max turns")


class ChatResponse(BaseModel):
    """Response from agent loop execution."""
    response: str = Field(..., description="Final response from agent")
    conversation_id: str = Field(..., description="Conversation ID")
    turns: int = Field(..., description="Number of agent loop turns")
    tool_calls: int = Field(..., description="Total tool calls executed")
    model: str = Field(..., description="LLM model used")


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(..., description="Service status")
    llm_connected: bool = Field(..., description="LLM endpoint reachable")
    mcp_servers: Dict[str, str] = Field(..., description="MCP server statuses")


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


@app.on_event("startup")
async def startup():
    """Initialize orchestrator on server startup."""
    global config, llm_adapter, mcp_orchestrator, tool_registry, agent_loop
    
    logger.info("Initializing Tarbar_AI Orchestrator...")
    
    config = OrchestratorConfig.from_env()
    llm_adapter = LLMAdapter(config.llm)
    mcp_orchestrator = MCPOrchestrator()
    tool_registry = ToolRegistry()
    agent_loop = AgentLoop(
        max_turns=config.agent_loop.max_turns,
        max_tool_calls_per_turn=config.agent_loop.max_tool_calls_per_turn,
        enable_tool_use=config.agent_loop.enable_tool_use,
    )
    
    # Initialize MCP server (Phase 1: single hardcoded server)
    try:
        mcp_config = MCPServerConfig(
            name="local-mcp",
            command="fastmcp run services/mcp/main.py:mcp",
            transport="stdio",
        )
        await mcp_orchestrator.initialize_server(mcp_config)
        logger.info("MCP server initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize MCP server: {e}")
    
    logger.info("Orchestrator initialization complete")


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on server shutdown."""
    global llm_adapter, mcp_orchestrator
    
    logger.info("Shutting down orchestrator...")
    
    if mcp_orchestrator:
        await mcp_orchestrator.shutdown_all()
    
    if llm_adapter:
        await llm_adapter.close()
    
    logger.info("Orchestrator shutdown complete")


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Execute agent loop for a user message.
    
    Returns the final response after tool use if applicable.
    """
    if not agent_loop or not llm_adapter or not mcp_orchestrator or not tool_registry:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")
    
    try:
        logger.info(f"Chat request: {request.message[:50]}...")
        
        # Override max turns if provided
        if request.max_turns:
            agent_loop.max_turns = request.max_turns
        
        # Run agent loop
        response, state = await agent_loop.run(
            user_message=request.message,
            llm_adapter=llm_adapter,
            mcp_orchestrator=mcp_orchestrator,
            tool_registry=tool_registry,
        )
        
        return ChatResponse(
            response=response,
            conversation_id=request.conversation_id or "default",
            turns=state.turn,
            tool_calls=state.total_tool_calls,
            model=config.llm.model,
        )
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=f"Agent execution failed: {str(e)}")


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


@app.get("/tools", response_model=ToolsResponse)
async def list_tools() -> ToolsResponse:
    """List available tools."""
    if not tool_registry:
        raise HTTPException(status_code=500, detail="Tool registry not initialized")
    
    tools = tool_registry.list_all_tools()
    
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


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Tarbar_AI Orchestrator",
        "version": "0.1.0",
        "endpoints": [
            "POST /chat — Execute agent loop",
            "GET /health — Health check",
            "GET /tools — List available tools",
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
