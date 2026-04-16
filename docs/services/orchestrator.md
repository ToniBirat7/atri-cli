# Orchestrator Service

The orchestrator is the control plane for Tarbar_AI. It owns request authentication, prompt policy selection, model execution, MCP tool routing, persistence, rate limiting, and telemetry.

## What It Does

The orchestrator receives chat requests from the frontend API route, normalizes the request, chooses the active prompt policy, runs the deterministic agent loop, and returns either a full response or a streaming SSE response. It also records conversation metadata and tool-call audit data for later inspection.

## Inputs and Outputs

Inputs:
- User message text
- Optional conversation ID
- Optional allowed filesystem root for MCP tools
- Optional prompt profile override
- Optional max turn override
- Authentication credentials

Outputs:
- Final assistant response
- Conversation ID
- Request correlation ID
- Turn and tool-call counts
- Streaming delta events when the streaming endpoint is used

## Internal Responsibilities

### Prompt policy
The orchestrator builds the system prompt from a named profile such as `general-purpose`, `hybrid`, or `legal-strict`. The prompt policy stays in the backend so policy decisions are consistent regardless of the frontend client.

### Authentication
The service supports JWT-based service-to-service authentication and a legacy API-key migration path. In production, JWT should be the default deployment mode.

### Persistence
Conversation headers, per-turn records, and tool-call audit rows are stored in the configured database. The default local developer path is sqlite, while production compose uses PostgreSQL.

### Rate limiting
The orchestrator enforces per-IP and per-path request limits. It uses Redis when enabled and falls back to a local in-memory limiter when Redis is unavailable.

### Observability
The service emits structured logs with request IDs and turn IDs, and it can bootstrap OpenTelemetry tracing for FastAPI and HTTPX.

## Configuration

Key environment variables:
- `LLM_BASE_URL` and `LLM_API_KEY` for the llama.cpp endpoint
- `PROMPT_POLICY_DEFAULT_PROFILE` for the default policy mode
- `ORCHESTRATOR_DATABASE_URL` for sqlite or PostgreSQL persistence
- `ORCHESTRATOR_AUTH_MODE` for `jwt`, `api-key`, or `hybrid`
- `ORCHESTRATOR_REDIS_URL` and `ORCHESTRATOR_REDIS_ENABLED` for distributed rate limiting
- `ORCHESTRATOR_TELEMETRY_ENABLED` and `ORCHESTRATOR_OTLP_ENDPOINT` for tracing

## Request Flow

1. The frontend sends a chat request to the orchestrator API route.
2. The orchestrator authenticates the caller and enforces rate limits.
3. The request message is normalized and a prompt profile is selected.
4. The system prompt is built and the agent loop is executed.
5. The LLM may emit tool calls, which are routed through the MCP registry.
6. Tool results are fed back into the agent loop until it finishes or exhausts budgets.
7. The final response is returned to the frontend and persisted in the database.

## Runtime Dependencies

- llama.cpp for model inference
- MCP server(s) for tool execution
- PostgreSQL for production persistence
- Redis for distributed rate limiting
- Tempo or another OTLP collector for tracing

## Operational Notes

- Keep prompt policy logic in the orchestrator, not in the frontend.
- Use `hybrid` mode only during migration.
- Keep the allowed filesystem root narrow when enabling filesystem tools.
- Prefer the streaming endpoint for interactive chat because it exposes incremental model output.
