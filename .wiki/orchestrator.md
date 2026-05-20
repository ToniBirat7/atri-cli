# Orchestrator

**File:** `services/orchestrator/api.py` (56 KB)  
**Port:** 8001  
**Framework:** FastAPI + uvicorn

## Key routes

| Method | Route | Auth required | Description |
|--------|-------|--------------|-------------|
| GET | `/` | No | Route listing |
| GET | `/health` | No | `{"status":"ok","llm_connected":bool}` |
| GET | `/ready` | No | `{"ready":bool,"llm_connected":bool,"mcp_servers":[...]}` |
| POST | `/chat` | Optional | Main agent endpoint — synchronous response |
| POST | `/chat/stream` | Optional | SSE streaming — `text/event-stream` |
| GET | `/tools` | Optional | List all available MCP tools |
| POST | `/tools/refresh` | Optional | Re-discover MCP tools, returns updated count |
| GET | `/metrics` | Optional | `{"uptime":float,"requests":int,...}` |
| POST | `/permissions/evaluate` | Optional | Evaluate a tool call permission decision |
| GET | `/conversations` | Optional | List conversation history |
| GET | `/mcp/startup-summary` | Optional | MCP server startup trace |

### `/chat` request body

```json
{
  "message": "string",
  "conversation_id": "uuid (optional — for multi-turn)",
  "max_turns": 10,
  "permission_mode": "default | bypassPermissions | acceptEdits",
  "allowed_directory": "/absolute/path",
  "prompt_profile": "agent-v3-26b"  // admin key required
}
```

### `/chat` response body

```json
{
  "response": "string",
  "conversation_id": "uuid",
  "turns": 3,
  "tool_calls": 5,
  "thinking": "string | null"
}
```

### `/chat/stream` — SSE format

Server-Sent Events stream. Each line is a typed event:
```
data: {"type":"content_delta","text":"Hello"}
data: {"type":"tool_call","name":"bash_exec","args":{...}}
data: {"type":"tool_result","name":"bash_exec","result":"..."}
data: [DONE]
```

### `/permissions/evaluate` request body

```json
{
  "tool_call": "Bash(echo hello)",
  "mode": "default"
}
```

Not `{"tool":"bash_exec","args":{}}` — that returns a 422.

## Request lifecycle

1. Auth middleware checks `X-API-Key` or `Authorization: Bearer <JWT>`
2. Prompt policy injects system prompt (profile lookup)
3. AgentLoop is instantiated with the current config
4. Loop runs until `NO_TOOL_CALLS` or budget exhausted
5. Turn history is persisted to SQLite (`orchestrator.db`)
6. Response serialized and returned

## Conversation persistence

Conversations stored in `runtime/state/orchestrator.db` (SQLite). Pass `conversation_id` in subsequent requests to continue a session. The orchestrator reloads message history from the DB and appends new turns.

## Related pages

- [[agent-loop]] — what the orchestrator invokes
- [[auth]] — middleware details
- [[prompt-policy]] — system prompt injection
- [[configuration]] — all .env tunables
