# Architecture

## Data flow

```
User keystroke
     │
     ▼
atri CLI (Rich TUI / --print mode)
     │  HTTP POST /chat or /chat/stream
     ▼
FastAPI Orchestrator  :8001
     │
     ├─ Auth layer  (JWT / API key / hybrid)
     ├─ Prompt policy  (profile → system prompt injection)
     │
     ▼
AgentLoop  (agent_loop.py)
     │
     │   ┌──────────────────────────────────────┐
     │   │  Turn N                               │
     │   │  1. Build messages array              │
     │   │  2. POST /v1/chat/completions → LLM   │
     │   │  3. Parse tool_calls from response    │
     │   │  4. Execute each tool via MCP         │
     │   │  5. Inject tool results into messages │
     │   │  6. Check TurnOutcome                 │
     │   └──────────────────────────────────────┘
     │
     │  repeat until: NO_TOOL_CALLS | MAX_TURNS_REACHED | ERROR
     │
     ├─────────────────────┐
     ▼                     ▼
llama-server  :8080      MCP server (in-process: local-mcp)
(Gemma 4 26B MoE)        32 tools: filesystem, bash, git,
OpenAI-compat /v1        grep, todo, web search, repo_map
```

## Service ports

| Service | Port | Notes |
|---------|------|-------|
| llama-server | 8080 | `.env` `LLM_BASE_URL=http://127.0.0.1:8080/v1` |
| orchestrator | 8001 | FastAPI, uvicorn |
| frontend (Next.js) | 3000 | optional dev mode |

## Key modules

| File | Role |
|------|------|
| `services/orchestrator/api.py` | FastAPI route definitions, request/response models |
| `services/orchestrator/agent_loop.py` | ReAct loop engine, TurnOutcome state machine |
| `services/orchestrator/llm_adapter.py` | HTTP client to llama-server (OpenAI compat) |
| `services/orchestrator/mcp_orchestrator.py` | Dispatches tool calls to MCP server |
| `services/orchestrator/config.py` | Pydantic config loaded from `.env` |
| `services/orchestrator/auth.py` | JWT + API key auth middleware |
| `services/orchestrator/prompt_policy.py` | Profile lookup and system prompt injection |
| `services/orchestrator/permissions.py` | Permission evaluation endpoint |
| `services/mcp/main.py` | All 32 tool implementations (FastMCP) |
| `services/mcp/diff_engine.py` | Diff/patch engine used by `edit_file` |
| `apps/cli/atri_cli/main.py` | CLI entry point (argparse, print mode) |
| `apps/cli/atri_cli/tui.py` / `rich_tui.py` | Terminal UI (Rich library) |
| `apps/cli/atri_cli/service_manager.py` | Start/stop llama-server + orchestrator |

## MCP transport

The `local-mcp` server is in-process (same Python process as orchestrator, stdio transport by default). External MCP servers can be configured via `MCP_SERVERS_JSON` in `.env`.

## Related pages

- [[agent-loop]] — TurnOutcome state machine detail
- [[mcp-tools]] — full tool catalog
- [[orchestrator]] — API routes
- [[llm-inference]] — llama-server launch flags
