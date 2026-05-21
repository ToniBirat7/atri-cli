# Architecture

## Data flow

```
User keystroke / --prompt flag
     │
     ▼
atri CLI  (apps/cli/atri_cli/main.py)
  Rich TUI | --print mode | slash commands | PLAN mode
  ServiceManager.ensure_running()  →  auto-start llama + orchestrator
     │  HTTP POST /chat/stream
     ▼
FastAPI Orchestrator  :8001  (api.py)
     │
     ├─ Auth layer  (JWT / API key / hybrid)  →  auth.py
     ├─ Rate limiting  (redis_rate_limit.py / in-memory fallback)
     ├─ Prompt policy  (prompt_policy.py)  →  profile → system prompt injection
     ├─ Skills loader  (skills_loader.py)  →  ~/.atri/skills/ + .atri/skills/
     ├─ Model router   (model_router.py)   →  per-request model selection
     │
     ▼
AgentLoop  (agent_loop.py)
     │
     │   HookRegistry (hooks.py) — beforeToolCall / afterToolCall interceptors
     │   SessionTree  (session_tree.py) — append-only JSONL, fork/branch
     │   Compaction   (compaction.py)  — auto-compact at token threshold
     │
     │   ┌──────────────────────────────────────────────┐
     │   │  Turn N                                       │
     │   │  1. Build messages array                      │
     │   │  2. maybe_compact_messages() if near limit    │
     │   │  3. POST /v1/chat/completions → LLM           │
     │   │  4. Parse tool_calls from response            │
     │   │  5. hook_registry.before_tool_call()          │
     │   │  6. Execute each tool via MCPOrchestrator     │
     │   │  7. hook_registry.after_tool_call()           │
     │   │  8. session_tree.append(entry)                │
     │   │  9. Inject tool results into messages         │
     │   │  10. Check TurnOutcome                        │
     │   └──────────────────────────────────────────────┘
     │
     │  repeat until: NO_TOOL_CALLS | MAX_TURNS_REACHED | PLANNING | ERROR
     │
     │  On session end (10+ turns): memory_service.maybe_mine_session()
     │
     ├─────────────────────────┐
     ▼                         ▼
llama-server  :8000          MCP server (in-process: local-mcp)
(Gemma 4 E2B)                services/mcp/main.py
OpenAI-compat /v1            32 tools: filesystem, bash, git,
Flash Attention, KV quant    grep, todo, web search, repo_map,
                             diff_engine, hash-anchored edit
     │
     ▼
SSE stream → atri CLI / Next.js frontend (:3000)
SQLite persistence (runtime/state/orchestrator.db)
```

## Event lifecycle

Each turn emits structured log events via `_log_event()` in `api.py`:

| Event | When |
|-------|------|
| `session.start` | New conversation created |
| `turn.start` | Agent loop iteration begins |
| `tool.before` | Hook intercept before tool execution |
| `tool.execute` | Tool dispatched to MCP server |
| `tool.after` | Hook intercept after result received |
| `turn.end` | Turn outcome determined |
| `session.compact` | Context compaction triggered |
| `session.end` | Conversation complete, memory mining triggered |

## Hook system

`hooks.py` provides two hook systems:

1. **HookManager** — in-process event bus used by `api.py` for lifecycle events (register/emit callbacks).
2. **HookRegistry** — `beforeToolCall` / `afterToolCall` interceptors in the agent loop. Built-in hooks handle:
   - Path protection (governance): block writes to paths outside the allowed directory
   - Tool call caching: skip redundant identical tool calls
   - Approval gates: prompt user for dangerous operations in `default` permission mode

Return `BLOCK` from a before-hook to cancel the tool call without executing it.

## Session tree

`session_tree.py` stores each turn as a `SessionEntry` node with UUID + `parent_id` pointer. Stored as append-only JSONL at `~/.atri/sessions/<session_id>.jsonl`. Forking creates a new session with the current node as parent.

## Service ports

| Service | Port | Notes |
|---------|------|-------|
| llama-server | **8000** | `.env` `LLM_BASE_URL=http://127.0.0.1:8000/v1` |
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
