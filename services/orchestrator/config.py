"""
Configuration schema for orchestrator service.

Defines pydantic models for LLM settings, MCP client settings, and agent loop parameters.
Loads from environment variables and config files.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
import os


class LLMConfig(BaseModel):
    """llama.cpp inference endpoint configuration."""

    base_url: str = Field(
        default="http://127.0.0.1:8000/v1",
        description="llama.cpp OpenAI-compatible API endpoint"
    )
    api_key: Optional[str] = Field(
        default=None,
        description="API key for llama.cpp (if required)"
    )
    model: str = Field(
        default="local-model",
        description="Model identifier"
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Sampling temperature"
    )
    max_tokens: int = Field(
        default=2048,
        ge=1,
        description="Maximum tokens per response"
    )
    timeout_seconds: int = Field(
        default=30,
        ge=1,
        description="Request timeout in seconds"
    )

    class Config:
        env_prefix = "LLM_"


class MCPConfig(BaseModel):
    """MCP server configuration."""

    servers: List[dict] = Field(
        default=[],
        description="List of MCP servers with startup commands and transport"
    )
    default_transport: str = Field(
        default="stdio",
        description="Default transport mode (stdio, sse, websocket)"
    )
    tool_timeout_seconds: int = Field(
        default=10,
        ge=1,
        description="Timeout for tool execution"
    )
    max_tool_call_retries: int = Field(
        default=2,
        ge=0,
        description="Max retries for failed tool calls"
    )

    class Config:
        env_prefix = "MCP_"


class AgentLoopConfig(BaseModel):
    """Agent loop and tool-calling budget configuration."""

    max_turns: int = Field(
        default=10,
        ge=1,
        description="Maximum agent loop turns"
    )
    max_tool_calls_per_turn: int = Field(
        default=3,
        ge=1,
        description="Max tool calls per agent turn"
    )
    enable_tool_use: bool = Field(
        default=True,
        description="Enable tool-calling mode"
    )
    stream_responses: bool = Field(
        default=False,
        description="Stream LLM responses (Phase 3+)"
    )

    class Config:
        env_prefix = "AGENT_"


class OrchestratorConfig(BaseModel):
    """Root orchestrator configuration."""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    agent_loop: AgentLoopConfig = Field(default_factory=AgentLoopConfig)
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR)"
    )
    enable_observability: bool = Field(
        default=True,
        description="Enable structured logging and metrics (Phase 7)"
    )

    class Config:
        env_file = ".env"
        case_sensitive = False

    @classmethod
    def from_env(cls) -> "OrchestratorConfig":
        """Load configuration from environment variables."""
        return cls(
            llm=LLMConfig(
                base_url=os.getenv("LLM_BASE_URL", "http://127.0.0.1:8000/v1"),
                api_key=os.getenv("LLM_API_KEY"),
                model=os.getenv("LLM_MODEL", "local-model"),
                temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),
                max_tokens=int(os.getenv("LLM_MAX_TOKENS", "2048")),
                timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "30")),
            ),
            mcp=MCPConfig(
                default_transport=os.getenv("MCP_DEFAULT_TRANSPORT", "stdio"),
                tool_timeout_seconds=int(os.getenv("MCP_TOOL_TIMEOUT_SECONDS", "10")),
                max_tool_call_retries=int(os.getenv("MCP_MAX_TOOL_CALL_RETRIES", "2")),
            ),
            agent_loop=AgentLoopConfig(
                max_turns=int(os.getenv("AGENT_MAX_TURNS", "10")),
                max_tool_calls_per_turn=int(os.getenv("AGENT_MAX_TOOL_CALLS_PER_TURN", "3")),
                enable_tool_use=os.getenv("AGENT_ENABLE_TOOL_USE", "true").lower() == "true",
                stream_responses=os.getenv("AGENT_STREAM_RESPONSES", "false").lower() == "true",
            ),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            enable_observability=os.getenv("ENABLE_OBSERVABILITY", "true").lower() == "true",
        )
