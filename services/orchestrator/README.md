# Orchestrator Service

**Phase 1 of 10-phase architecture** — Core LLM + MCP orchestration for Tarbar_AI.

For the production-oriented service reference, see [docs/services/orchestrator.md](../../docs/services/orchestrator.md).

## Overview

The orchestrator service is the **brain** of Tarbar_AI. It coordinates:

1. **LLM Inference** (llama.cpp) — Chat completions with tool calling
2. **Tool Execution** (MCP) — Routing and executing tools from MCP servers
3. **Deterministic Agent Loop** — Manages multi-turn conversations with tool use

## Components

### `config.py`
Configuration schema using Pydantic. Loads from environment variables:
- **LLMConfig** — llama.cpp endpoint, API key, sampling params
- **MCPConfig** — MCP server endpoints, tool timeouts, retries
- **AgentLoopConfig** — Budget controls (max turns, tool calls per turn)

**Environment variables:**
```bash
LLM_BASE_URL=http://127.0.0.1:8000/v1
LLM_API_KEY=secret
LLM_TEMPERATURE=0.7
MCP_TOOL_TIMEOUT_SECONDS=10
AGENT_MAX_TURNS=10
AGENT_MAX_TOOL_CALLS_PER_TURN=3
```

### `llm_adapter.py`
Abstracts llama.cpp OpenAI-compatible API:
- Chat completions with tool schemas
- Tool call extraction from LLM responses
- Response formatting for multi-turn conversations

**Phase 1:** Non-streamed tool calling for reliability.  
**Phase 3:** Streaming responses via SSE.

### `mcp_orchestrator.py`
Manages MCP server lifecycle and tool execution:
- Server initialization and discovery
- Tool call routing to correct server
- Error handling and resilience

**Phase 1:** Single MCP server (STDIO transport).  
**Phase 4:** Multi-server support with tool namespacing.

### `tool_registry.py`
Central registry of all available tools:
- Registers tools from MCP server discovery
- Translates MCP schemas to OpenAI format
- Provides tool lookup and filtering
- Supports namespaced tool aliases (`server_name.tool_name`) for multi-server routing

**Phase 1:** Basic registry.  
**Phase 6:** Access control and risk tiers (green/yellow/red).

### `agent_loop.py`
Deterministic agentic AI loop:

1. User message → LLM (with tools)
2. LLM responds (with or without tool calls)
3. Tool execution (max `max_tool_calls_per_turn` per turn)
4. Tool results → LLM context
5. Repeat until max turns or no tool calls

**Budgets:**
- `max_turns` — Total agent loop iterations
- `max_tool_calls_per_turn` — Tools executed per turn
- `timeout_seconds` — Per-tool execution timeout

### `permissions.py`
Incremental permission rule evaluator used by API and CLI:
- rule precedence: deny > ask > allow
- mode-aware behavior (`default`, `plan`, `dontAsk`, `acceptEdits`, `bypassPermissions`)
- glob-style matching for rule specifiers

### `api.py`
FastAPI HTTP server exposing orchestrator:

**Endpoints:**
- `POST /chat` — Execute agent loop
- `POST /chat/stream` — Stream chat response as SSE
- `GET /health` — Health check (LLM + MCP servers)
- `GET /live` — Liveness probe
- `GET /ready` — Readiness probe
- `GET /tools` — List available tools
- `GET /conversations` — List stored conversations and prompt profiles
- `GET /conversations/{id}` — Conversation details and turn transcript
- `POST /conversations/{id}/resume` — Validate resumable conversation metadata
- `POST /conversations/{id}/fork` — Fork conversation into a new session id
- `POST /permissions/evaluate` — Evaluate a tool call against mode and rule sets
- `GET /metrics` — Runtime counters and uptime
- `GET /` — Service info

Operational defaults:
- If `allowed_directory` is omitted in `POST /chat`, the orchestrator sets a safe default root to the workspace directory.
- If `allowed_directory` is provided, that value is applied for the request before tool execution.
- Request logs are emitted as JSON events with `request_id`; turn-level events include `turn_id`.
- `POST /chat` responses include `request_id` for log correlation.

Security policy:
- `ORCHESTRATOR_AUTH_MODE` controls the auth strategy. Use `hybrid` during migration, `jwt` for strict service-to-service auth, or `api-key` for local-only bootstrap.
- If `ORCHESTRATOR_JWT_SECRET` is set, `Authorization: Bearer <jwt>` tokens are validated with `iss`, `aud`, and `sub` claims.
- If `ORCHESTRATOR_API_KEY` is set, the legacy API-key path remains available in `hybrid` or `api-key` mode.
- If `ORCHESTRATOR_ADMIN_API_KEY` is set, it unlocks per-request prompt profile overrides for privileged clients.
- If `ORCHESTRATOR_RATE_LIMIT_PER_MINUTE` is greater than zero, those same endpoints are rate-limited per client IP and path.
- `GET /health` and `GET /` remain unauthenticated by default so local monitoring stays simple.

Prompt policy:
- `PROMPT_POLICY_DEFAULT_PROFILE` selects the default behavior (`general-purpose`, `legal-strict`, or `hybrid`).
- `PROMPT_POLICY_FALLBACK_TEXT`, `PROMPT_POLICY_DISCLAIMER_TEXT`, and `PROMPT_POLICY_LEGAL_HELP_LINE` control the legal-safety messaging without editing code.
- The Gemma 4 llama.cpp Jinja template accepts system content in the first system turn and injects tool declarations there, so prompts stay plain text and do not embed tool markup directly.

Persistence:
- `ORCHESTRATOR_DATABASE_URL` defaults to `sqlite:///orchestrator.db` for local persistence.
- Production compose uses PostgreSQL through `postgresql://...`.
- Set `ORCHESTRATOR_ENABLE_PERSISTENCE=false` to disable conversation and turn recording.
- Each `/chat` or `/chat/stream` request stores the conversation metadata, turn history, and tool-call audit trail.

Rate limiting and tracing:
- `ORCHESTRATOR_REDIS_URL` and `ORCHESTRATOR_REDIS_ENABLED` enable distributed request limiting.
- `ORCHESTRATOR_TELEMETRY_ENABLED` and `ORCHESTRATOR_OTLP_ENDPOINT` configure OpenTelemetry export.
Multi-server routing:
- Configure multiple MCP servers with `MCP_SERVERS_JSON` (JSON array of `{name, command, transport}` objects).
- Tool registry always publishes namespaced aliases (`server.tool`) and uses plain aliases only when no collision exists.
- Agent loop resolves tool calls through the registry, then routes execution to the correct MCP server.

## Running the Orchestrator

### Prerequisites
1. **llama.cpp server** running on `127.0.0.1:8000` with `--jinja` flag
2. **MCP server** available (e.g., `services/mcp/main.py:mcp`)

### Startup

```bash
cd services/orchestrator

# Install dependencies
pip install -r requirements.txt

# Run orchestrator API
python -m uvicorn api:app --host 127.0.0.1 --port 8001 --reload

# OR use the root Makefile (Phase 1)
make orchestrator
```

### Test Endpoints

```bash
# Health check
curl http://127.0.0.1:8001/health

# List tools
curl http://127.0.0.1:8001/tools

# Chat request
curl -X POST http://127.0.0.1:8001/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello, what tools do you have?"}'

# Chat request with explicit tool sandbox root
curl -X POST http://127.0.0.1:8001/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "List files in /tmp", "allowed_directory": "/tmp"}'
```

## Architecture Roadmap

| Phase  | Focus                                                              | Status        |
| ------ | ------------------------------------------------------------------ | ------------- |
| **1**  | Core modules (LLM adapter, MCP orchestrator, agent loop, registry) | 🔄 Scaffolding |
| **2**  | MCP client integration (actual tool discovery/execution)           | ⏳ Pending     |
| **3**  | Streaming responses, error recovery, multi-turn state              | ⏳ Pending     |
| **4**  | Multi-MCP-server support, tool namespacing, routing                | ⏳ Pending     |
| **5**  | Resilience (retry, circuit-breaker, observability)                 | ⏳ Pending     |
| **6**  | Tool access control, risk tiers, policy enforcement                | ⏳ Pending     |
| **7**  | Full observability (structured logging, metrics, tracing)          | ⏳ Pending     |
| **8**  | Testing & evals harness, benchmark suite                           | ⏳ Pending     |
| **9**  | Scale path (containerization, K8s deployment, multi-region)        | ⏳ Pending     |
| **10** | Production rollout (green/yellow/red tiers, SLA monitoring)        | ⏳ Pending     |

## Next Steps (Phase 2)

1. Integrate actual MCP client SDK (when available)
2. Implement tool discovery from MCP servers
3. Wire MCP tool execution into agent loop
4. Add comprehensive unit tests
5. Test end-to-end flow: User message → LLM → MCP tool → Response

## Configuration for Development

Create `.env` file in `services/orchestrator/`:

```env
# llama.cpp
LLM_BASE_URL=http://127.0.0.1:8000/v1
LLM_API_KEY=secret
LLM_MODEL=local-model
LLM_TEMPERATURE=0.7
LLM_MAX_TOKENS=2048

# MCP
MCP_TOOL_TIMEOUT_SECONDS=10
MCP_MAX_TOOL_CALL_RETRIES=2

# Agent
AGENT_MAX_TURNS=10
AGENT_MAX_TOOL_CALLS_PER_TURN=3
AGENT_ENABLE_TOOL_USE=true

# Prompt policy
PROMPT_POLICY_DEFAULT_PROFILE=general-purpose
PROMPT_POLICY_FALLBACK_TEXT=मलाई यस बारेमा जानकारी उपलब्ध छैन।
PROMPT_POLICY_DISCLAIMER_TEXT=यो जानकारी मार्गदर्शनका लागि मात्र हो, कानूनी सल्लाह होइन।
PROMPT_POLICY_LEGAL_HELP_LINE=For human help, call 1660-01-333-55.

# Persistence and auth
ORCHESTRATOR_DATABASE_URL=sqlite:///orchestrator.db
ORCHESTRATOR_ENABLE_PERSISTENCE=true
ORCHESTRATOR_AUTH_MODE=hybrid
ORCHESTRATOR_JWT_SECRET=replace-with-a-long-random-secret
ORCHESTRATOR_JWT_ISSUER=tarbar-ai
ORCHESTRATOR_JWT_AUDIENCE=tarbar-ai-orchestrator
ORCHESTRATOR_SERVICE_SUBJECT=orchestrator-service

# Observability
LOG_LEVEL=DEBUG
ENABLE_OBSERVABILITY=true
```

## Testing

```bash
# Run unit tests (Phase 3+)
pytest tests/

# With coverage
pytest tests/ --cov=. --cov-report=html
```

## See Also

- [Architecture Plan](../../docs/architecture-plan.md) — Full 10-phase roadmap
- [MCP Service](../mcp/README.md) — Tool provider
- [Frontend](../../apps/frontend/) — User interface
- [llama.cpp Runtime](../../runtime/llm/README.md) — LLM inference
