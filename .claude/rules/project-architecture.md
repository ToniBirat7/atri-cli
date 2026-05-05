---
paths:
  - "services/**"
  - "apps/cli/atri_cli/**"
  - "services/orchestrator/**"
  - "services/mcp/**"
---

# Architecture Rules

## Data Flow
```
User Input
  → CLI (apps/cli/atri_cli/main.py) [TUI / --print mode]
  → ServiceManager.ensure_running() [starts llama-server + uvicorn if not alive]
  → HTTP POST /chat/stream (orchestrator:8001)
  → api.py: _authenticate_request() → _enforce_rate_limit() → _run_agent_request()
  → AgentLoop.run() [multi-turn ReAct]
    → LLMAdapter.chat_completion() → llama-server:8000/v1/chat/completions
    → LLMAdapter.extract_tool_calls()
    → MCPOrchestrator.execute_tool(server="local-mcp", tool=..., input=...)
    → FastMCP local-mcp (services/mcp/main.py) → filesystem / Tavily / DiffEngine
    → Tool result appended to messages
    → Next turn until: no tool calls OR max_turns reached
  → SSE stream of events back to client
  → OrchestratorDatabase.record_turn() [persist to SQLite/Postgres]
```

## Module Boundaries
- `api.py` is the only module that instantiates `AgentLoop`, `LLMAdapter`, `MCPOrchestrator` — they are singletons created at startup
- `agent_loop.py` never imports from `api.py` — dependency flows one way
- `mcp_orchestrator.py` manages server lifecycle and tool dispatch; never call FastMCP tools directly from `api.py`
- `prompt_policy.py` is the only place that builds system prompts — never construct system prompts inline in api.py or agent_loop.py
- `config.py` / `OrchestratorConfig.from_env()` is the single source of truth for all settings

## Dual Import Pattern (Required in every orchestrator module)
```python
try:
    from .module_name import Thing
except ImportError:
    from module_name import Thing
```
This is intentional — the orchestrator runs both as a package (tests) and directly via `uvicorn api:app`.

## Adding New MCP Tools
1. Add the tool function in `services/mcp/main.py` decorated with `@mcp.tool()`
2. Tool name becomes the MCP call name — keep it `snake_case`
3. Use `_resolve_path()` for all filesystem operations to enforce sandbox
4. Update `MCP_REQUIRED_TOOLS` set in `api.py` if it's a required capability
5. Test with: `cd services/mcp && fastmcp run main.py:mcp` in dev mode

## Adding New API Endpoints
1. Add Pydantic request/response models in `api.py`
2. Add the route handler with `@app.get/post/delete(...)`
3. Call `_authenticate_request()` for protected routes
4. Emit structured log events with `_log_event("event.name", **fields)`
5. Update `CLAUDE.md` key files if it's a major endpoint

## Permission Model
- `permission_mode="default"`: Agent asks before destructive operations
- `permission_mode="bypassPermissions"`: All tools execute without prompts (CLI benchmarking, trusted scripts)
- `permission_mode="acceptEdits"`: Auto-accept file edits, prompt for other ops
- Profile override (`prompt_profile`) requires `is_admin=True` — only granted with `ORCHESTRATOR_ADMIN_API_KEY`
