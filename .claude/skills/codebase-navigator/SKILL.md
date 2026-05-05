---
name: codebase-navigator
description: Use when you need to understand how a feature is implemented or find where specific logic lives. Triggers on questions like "where is X handled", "how does Y work", "find the code that does Z".
---

# Codebase Navigator

When asked to find or understand existing code, start from these entry points:

| Domain | Entry Point |
|--------|------------|
| API routes | `services/orchestrator/api.py` (all `@app.get/post` decorators) |
| Agent logic | `services/orchestrator/agent_loop.py` (`AgentLoop.run()`) |
| LLM calls | `services/orchestrator/llm_adapter.py` (`chat_completion`, `extract_tool_calls`) |
| MCP tools | `services/mcp/main.py` (all `@mcp.tool()` functions) |
| Tool dispatch | `services/orchestrator/mcp_orchestrator.py` (`execute_tool`) |
| Prompt building | `services/orchestrator/prompt_policy.py` (`build_system_prompt`) |
| Config | `services/orchestrator/config.py` (`OrchestratorConfig`) |
| Auth | `services/orchestrator/auth.py` (`RequestAuthenticator.authenticate`) |
| CLI TUI | `apps/cli/atri_cli/main.py` (`_run_interactive`, `_run_print_mode`) |
| Service startup | `apps/cli/atri_cli/service_manager.py` (`ServiceManager.ensure_running`) |
| Frontend chat | `apps/frontend/src/lib/useChat.ts` |
| SSE proxy | `apps/frontend/src/app/api/chat/route.ts` |

## Search Commands
```bash
# Find all API routes
grep -n "@app\." services/orchestrator/api.py

# Find a specific MCP tool
grep -n "def <tool_name>" services/mcp/main.py

# Find where a config value is used
grep -rn "<config_key>" services/ apps/cli/atri_cli/

# Find frontend component usage
grep -rn "<ComponentName" apps/frontend/src/
```

## Trace a Full Request
1. User types in TUI → `_run_interactive()` in `main.py`
2. Message sent via HTTP to orchestrator → `_build_payload()` in `main.py`
3. Received at `POST /chat` or `POST /chat/stream` in `api.py`
4. `_run_agent_request()` → `AgentLoop.run()` in `agent_loop.py`
5. LLM call → `LLMAdapter.chat_completion()` in `llm_adapter.py`
6. Tool calls → `MCPOrchestrator.execute_tool()` → FastMCP in `services/mcp/main.py`
7. Response persisted → `OrchestratorDatabase.record_turn()` in `database.py`

Never guess. Always read the actual file at the path shown above.
