# Configuration

**Files:**
- `services/orchestrator/.env` — live values (not committed)
- `services/orchestrator/.env.example` — template
- `services/orchestrator/config.py` — Pydantic schema, env var names

## All environment variables

### LLM (llama-server connection)

| Variable                  | Default                    | Notes                                                  |
| ------------------------- | -------------------------- | ------------------------------------------------------ |
| `LLM_BASE_URL`            | `http://127.0.0.1:8000/v1` | **Must be patched to :8080** for current launch config |
| `LLM_API_KEY`             | —                          | Must match `--api-key` on llama-server                 |
| `LLM_MODEL`               | `local-model`              | Sent in requests; llama-server ignores it              |
| `LLM_TEMPERATURE`         | `0.6`                      | Agent tool-call turns; use 1.0 for creative chat       |
| `LLM_TOP_P`               | `0.95`                     | Nucleus sampling                                       |
| `LLM_TOP_K`               | `64`                       | Top-k cutoff                                           |
| `LLM_MAX_TOKENS`          | `2048` (code default)      | Max tokens per response                                |
| `LLM_TIMEOUT_SECONDS`     | `30` (code default)        | **Patch to 300 for 26B model**                         |
| `LLM_PARALLEL_TOOL_CALLS` | `true`                     | Allow multiple tools per turn                          |

### Agent loop

| Variable | Default | Notes |
|----------|---------|-------|
| `AGENT_MAX_TURNS` | `10` | Max ReAct iterations |
| `AGENT_MAX_TOOL_CALLS_PER_TURN` | `3` | Budget per turn |
| `AGENT_ENABLE_TOOL_USE` | `true` | Enable tool-calling |
| `AGENT_THINKING_MODE` | `tool_calls_off` | `off` / `tool_calls_off` / `always` |
| `AGENT_STREAM_RESPONSES` | `false` | Streaming mode |

### MCP

| Variable | Default | Notes |
|----------|---------|-------|
| `MCP_SERVERS_JSON` | `[]` | JSON array of external MCP server configs |
| `MCP_DEFAULT_TRANSPORT` | `stdio` | Transport for MCP servers |
| `MCP_TOOL_TIMEOUT_SECONDS` | `10` | Hard kill on tool execution |
| `MCP_MAX_TOOL_CALL_RETRIES` | `2` | Retry on tool error |
| `MCP_DISCOVERY_CACHE_TTL_SECONDS` | `30` | Tool list refresh interval |

### Prompt policy

| Variable | Default | Notes |
|----------|---------|-------|
| `PROMPT_POLICY_DEFAULT_PROFILE` | `general-purpose` | Set to `agent-v3-26b` for 26B model |

### Database

| Variable | Default |
|----------|---------|
| `ORCHESTRATOR_DATABASE_URL` | `sqlite:///runtime/state/orchestrator.db` |
| `ORCHESTRATOR_ENABLE_PERSISTENCE` | `true` |

### Auth & security

| Variable | Notes |
|----------|-------|
| `ORCHESTRATOR_AUTH_MODE` | `hybrid` (jwt \| api-key \| hybrid) |
| `ORCHESTRATOR_JWT_SECRET` | Shared HMAC secret |
| `ORCHESTRATOR_API_KEY` | Regular user API key |
| `ORCHESTRATOR_ADMIN_API_KEY` | Admin key — required for `prompt_profile` overrides |
| `ORCHESTRATOR_RATE_LIMIT_PER_MINUTE` | `0` = disabled |

### Other

| Variable | Default |
|----------|---------|
| `LOG_LEVEL` | `INFO` |
| `ENABLE_OBSERVABILITY` | `true` |
| `TAVILY_API_KEY` | Required for `search_web` tool |

## Current live values (2026-05-20)

As of the E2E test session:
```
LLM_BASE_URL=http://127.0.0.1:8080/v1
LLM_TIMEOUT_SECONDS=300
AGENT_THINKING_MODE=tool_calls_off
PROMPT_POLICY_DEFAULT_PROFILE=agent-v3-26b
ORCHESTRATOR_DATABASE_URL=sqlite:///runtime/state/orchestrator.db
```

## Related pages

- [[llm-inference]] — launch flags that must match LLM_BASE_URL / LLM_API_KEY
- [[prompt-policy]] — PROMPT_POLICY_* variables
- [[auth]] — auth mode details
- [[known-issues]] — port mismatch and timeout bugs
