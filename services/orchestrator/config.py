"""
Configuration schema for orchestrator service.

Defines pydantic models for LLM settings, MCP client settings, and agent loop parameters.
Loads from environment variables and config files.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
import os
import json
from pathlib import Path

from dotenv import load_dotenv


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
        default=0.6,
        ge=0.0,
        le=2.0,
        description="Sampling temperature (0.6 for agent tool-call turns; use 1.0 for creative/chat)"
    )
    top_p: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="Nucleus sampling probability"
    )
    top_k: int = Field(
        default=64,
        ge=1,
        description="Top-k sampling cutoff"
    )
    max_tokens: int = Field(
        default=4096,
        ge=1,
        description="Maximum tokens per response"
    )
    timeout_seconds: int = Field(
        default=120,
        ge=1,
        description="Request timeout in seconds"
    )
    parallel_tool_calls: bool = Field(
        default=True,
        description="Allow multiple independent tool calls in a single turn"
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
    startup_max_attempts: int = Field(
        default=3,
        ge=1,
        description="Maximum startup initialization attempts per MCP server"
    )
    startup_initial_backoff_seconds: float = Field(
        default=1.0,
        ge=0.0,
        description="Initial backoff for MCP startup retries"
    )
    startup_max_backoff_seconds: float = Field(
        default=8.0,
        ge=0.0,
        description="Maximum backoff for MCP startup retries"
    )
    discovery_cache_ttl_seconds: int = Field(
        default=30,
        ge=0,
        description="Tool discovery cache TTL in seconds; 0 disables cache"
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
    thinking_mode: str = Field(
        default="tool_calls_off",
        description=(
            "Gemma 4 reasoning mode. "
            "'off' = never think; "
            "'tool_calls_off' = think only on final user-facing turns; "
            "'always' = think on every turn."
        )
    )
    stream_responses: bool = Field(
        default=False,
        description="Stream LLM responses (Phase 3+)"
    )

    class Config:
        env_prefix = "AGENT_"


class PromptPolicyConfig(BaseModel):
    """Prompt policy and safety defaults."""

    default_profile: str = Field(
        default="general-purpose",
        description="Default prompt profile used when no override is provided"
    )
    fallback_text: str = Field(
        default="मलाई यस बारेमा जानकारी उपलब्ध छैन।",
        description="Fallback text for unsupported or missing legal context"
    )
    disclaimer_text: str = Field(
        default="यो जानकारी मार्गदर्शनका लागि मात्र हो, कानूनी सल्लाह होइन।",
        description="Safety disclaimer appended to legal responses"
    )
    legal_help_line: str = Field(
        default="For human help, call 1660-01-333-55.",
        description="Human handoff line for legal-support responses"
    )


class DatabaseConfig(BaseModel):
    """Conversation persistence configuration."""

    url: str = Field(
        default="sqlite:///runtime/state/orchestrator.db",
        description="Database URL used for conversation persistence"
    )
    enable_persistence: bool = Field(
        default=True,
        description="Enable conversation/turn persistence"
    )


class AuthConfig(BaseModel):
    """JWT and service-to-service authentication configuration."""

    mode: str = Field(
        default="hybrid",
        description="Authentication mode (jwt, api-key, hybrid)"
    )
    jwt_secret: Optional[str] = Field(
        default=None,
        description="Shared secret for signing and validating HMAC JWTs"
    )
    jwt_issuer: str = Field(
        default="atri-code",
        description="Expected JWT issuer"
    )
    jwt_audience: str = Field(
        default="atri-code-orchestrator",
        description="Expected JWT audience"
    )
    service_subject: str = Field(
        default="orchestrator-service",
        description="Subject identifier for service-to-service requests"
    )


class RedisConfig(BaseModel):
    """Redis configuration for distributed rate limiting and shared state."""

    url: Optional[str] = Field(
        default=None,
        description="Redis URL used for distributed rate limiting"
    )
    enabled: bool = Field(
        default=False,
        description="Enable Redis-backed features when available"
    )


class TelemetryConfig(BaseModel):
    """OpenTelemetry configuration."""

    enabled: bool = Field(
        default=True,
        description="Enable OpenTelemetry bootstrap"
    )
    otlp_endpoint: Optional[str] = Field(
        default=None,
        description="OTLP HTTP collector endpoint"
    )


class SecurityConfig(BaseModel):
    """Orchestrator security and access policy."""

    api_key: Optional[str] = Field(
        default=None,
        description="Optional API key required for protected endpoints"
    )
    admin_api_key: Optional[str] = Field(
        default=None,
        description="Optional admin-only API key for privileged per-request overrides"
    )
    rate_limit_per_minute: int = Field(
        default=0,
        ge=0,
        description="Maximum requests per minute per client IP; 0 disables rate limiting"
    )
    allow_unauthenticated_health: bool = Field(
        default=True,
        description="Allow /health and / endpoints without authentication"
    )


class HookConfig(BaseModel):
    """Hook framework configuration."""

    enabled: bool = Field(
        default=True,
        description="Enable orchestrator hook events"
    )


class ManagedSettingsConfig(BaseModel):
    """Paths for configuration scope overlays."""

    user_path: Optional[str] = Field(default=None)
    project_path: Optional[str] = Field(default=None)
    local_path: Optional[str] = Field(default=None)
    managed_path: Optional[str] = Field(default=None)


class OrchestratorConfig(BaseModel):
    """Root orchestrator configuration."""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    agent_loop: AgentLoopConfig = Field(default_factory=AgentLoopConfig)
    prompt_policy: PromptPolicyConfig = Field(default_factory=PromptPolicyConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    hooks: HookConfig = Field(default_factory=HookConfig)
    managed_settings: ManagedSettingsConfig = Field(default_factory=ManagedSettingsConfig)
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
        env_path = Path(__file__).resolve().parent / ".env"
        load_dotenv(dotenv_path=env_path, override=False)

        mcp_servers = _safe_parse_json_array(os.getenv("MCP_SERVERS_JSON", "[]"))

        base_config = cls(
            llm=LLMConfig(
                base_url=os.getenv("LLM_BASE_URL", "http://127.0.0.1:8000/v1"),
                api_key=os.getenv("LLM_API_KEY"),
                model=os.getenv("LLM_MODEL", "local-model"),
                temperature=float(os.getenv("LLM_TEMPERATURE", "0.6")),
                top_p=float(os.getenv("LLM_TOP_P", "0.95")),
                top_k=int(os.getenv("LLM_TOP_K", "64")),
                max_tokens=int(os.getenv("LLM_MAX_TOKENS", "2048")),
                timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "30")),
                parallel_tool_calls=os.getenv("LLM_PARALLEL_TOOL_CALLS", "true").lower() == "true",
            ),
            mcp=MCPConfig(
                servers=mcp_servers,
                default_transport=os.getenv("MCP_DEFAULT_TRANSPORT", "stdio"),
                tool_timeout_seconds=int(os.getenv("MCP_TOOL_TIMEOUT_SECONDS", "10")),
                max_tool_call_retries=int(os.getenv("MCP_MAX_TOOL_CALL_RETRIES", "2")),
                startup_max_attempts=int(os.getenv("MCP_STARTUP_MAX_ATTEMPTS", "3")),
                startup_initial_backoff_seconds=float(os.getenv("MCP_STARTUP_INITIAL_BACKOFF_SECONDS", "1.0")),
                startup_max_backoff_seconds=float(os.getenv("MCP_STARTUP_MAX_BACKOFF_SECONDS", "8.0")),
                discovery_cache_ttl_seconds=int(os.getenv("MCP_DISCOVERY_CACHE_TTL_SECONDS", "30")),
            ),
            agent_loop=AgentLoopConfig(
                max_turns=int(os.getenv("AGENT_MAX_TURNS", "10")),
                max_tool_calls_per_turn=int(os.getenv("AGENT_MAX_TOOL_CALLS_PER_TURN", "3")),
                enable_tool_use=os.getenv("AGENT_ENABLE_TOOL_USE", "true").lower() == "true",
                thinking_mode=os.getenv("AGENT_THINKING_MODE", "tool_calls_off"),
                stream_responses=os.getenv("AGENT_STREAM_RESPONSES", "false").lower() == "true",
            ),
            prompt_policy=PromptPolicyConfig(
                default_profile=os.getenv("PROMPT_POLICY_DEFAULT_PROFILE", "general-purpose"),
                fallback_text=os.getenv("PROMPT_POLICY_FALLBACK_TEXT", "मलाई यस बारेमा जानकारी उपलब्ध छैन।"),
                disclaimer_text=os.getenv("PROMPT_POLICY_DISCLAIMER_TEXT", "यो जानकारी मार्गदर्शनका लागि मात्र हो, कानूनी सल्लाह होइन।"),
                legal_help_line=os.getenv("PROMPT_POLICY_LEGAL_HELP_LINE", "For human help, call 1660-01-333-55."),
            ),
            database=DatabaseConfig(
                url=os.getenv("ORCHESTRATOR_DATABASE_URL", "sqlite:///runtime/state/orchestrator.db"),
                enable_persistence=os.getenv("ORCHESTRATOR_ENABLE_PERSISTENCE", "true").lower() == "true",
            ),
            auth=AuthConfig(
                mode=os.getenv("ORCHESTRATOR_AUTH_MODE", "hybrid"),
                jwt_secret=os.getenv("ORCHESTRATOR_JWT_SECRET"),
                jwt_issuer=os.getenv("ORCHESTRATOR_JWT_ISSUER", "atri-code"),
                jwt_audience=os.getenv("ORCHESTRATOR_JWT_AUDIENCE", "atri-code-orchestrator"),
                service_subject=os.getenv("ORCHESTRATOR_SERVICE_SUBJECT", "orchestrator-service"),
            ),
            redis=RedisConfig(
                url=os.getenv("ORCHESTRATOR_REDIS_URL"),
                enabled=os.getenv("ORCHESTRATOR_REDIS_ENABLED", "false").lower() == "true",
            ),
            telemetry=TelemetryConfig(
                enabled=os.getenv("ORCHESTRATOR_TELEMETRY_ENABLED", "true").lower() == "true",
                otlp_endpoint=os.getenv("ORCHESTRATOR_OTLP_ENDPOINT"),
            ),
            security=SecurityConfig(
                api_key=os.getenv("ORCHESTRATOR_API_KEY"),
                admin_api_key=os.getenv("ORCHESTRATOR_ADMIN_API_KEY"),
                rate_limit_per_minute=int(os.getenv("ORCHESTRATOR_RATE_LIMIT_PER_MINUTE", "0")),
                allow_unauthenticated_health=os.getenv("ORCHESTRATOR_ALLOW_UNAUTHENTICATED_HEALTH", "true").lower() == "true",
            ),
            hooks=HookConfig(
                enabled=os.getenv("ORCHESTRATOR_HOOKS_ENABLED", "true").lower() == "true",
            ),
            managed_settings=ManagedSettingsConfig(
                user_path=os.getenv("ORCHESTRATOR_SETTINGS_USER_PATH"),
                project_path=os.getenv("ORCHESTRATOR_SETTINGS_PROJECT_PATH"),
                local_path=os.getenv("ORCHESTRATOR_SETTINGS_LOCAL_PATH"),
                managed_path=os.getenv("ORCHESTRATOR_MANAGED_SETTINGS_PATH"),
            ),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            enable_observability=os.getenv("ENABLE_OBSERVABILITY", "true").lower() == "true",
        )

        try:
            from .settings_layer import apply_overlays_from_files
        except ImportError:
            from settings_layer import apply_overlays_from_files

        model_dump = getattr(base_config, "model_dump", None)
        base_data = model_dump() if callable(model_dump) else base_config.dict()  # type: ignore[attr-defined]

        overlay_paths: dict[str, Path] = {}
        if base_config.managed_settings.user_path:
            overlay_paths["user"] = Path(base_config.managed_settings.user_path)
        if base_config.managed_settings.project_path:
            overlay_paths["project"] = Path(base_config.managed_settings.project_path)
        if base_config.managed_settings.local_path:
            overlay_paths["local"] = Path(base_config.managed_settings.local_path)
        if base_config.managed_settings.managed_path:
            overlay_paths["managed"] = Path(base_config.managed_settings.managed_path)

        merged = apply_overlays_from_files(base_data, overlay_paths)
        return cls(**merged)


def _safe_parse_json_array(raw_value: str) -> List[dict]:
    """Parse a JSON array environment variable into a list of dicts."""
    try:
        parsed = json.loads(raw_value)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    except json.JSONDecodeError:
        pass
    return []
