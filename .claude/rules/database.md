---
paths:
  - "runtime/state/**"
  - "services/orchestrator/database.py"
  - "**/orchestrator.db"
  - "**/migration*"
---

# Database Rules

## ORM / Persistence Layer
`OrchestratorDatabase` (services/orchestrator/database.py) — raw aiosqlite / asyncpg queries, no ORM. Schema is auto-created at startup via `await conversation_store.initialize()`.

## Models
- **conversations**: `id`, `prompt_profile`, `created_at`, `updated_at`
- **turns**: `id`, `conversation_id` (FK), `request_id`, `turn_index`, `user_message`, `assistant_response`, `status`, `total_tool_calls`, `model`, `system_prompt`, `turn_history` (JSON), `tool_events` (JSON), `created_at`

## Connection URLs
| Environment | URL |
|------------|-----|
| Local dev | `sqlite:///runtime/state/orchestrator.db` |
| Docker | `postgresql://atri:atri@postgres:5432/atri` |
| Custom | Set `ORCHESTRATOR_DATABASE_URL` |

## Querying Patterns
- All DB access is async — use `await conversation_store.method()`
- `build_chat_history_messages(conversation_id, max_turns=10)` returns OpenAI-formatted message list for prior context injection
- Never query the DB from `agent_loop.py` — only `api.py` reads/writes the store

## Session State
- `runtime/state/code_index.db` — Tree-sitter code index (V2 intelligence feature)
- `runtime/state/.gitkeep` — Directory exists in git; actual DB files are gitignored

## Schema Changes
1. Modify `database.py` `CREATE TABLE` statements in `initialize()`
2. No migration tooling exists yet — for destructive changes, delete `runtime/state/orchestrator.db` and restart
3. In Docker/Postgres, manually run ALTER TABLE or drop and recreate

## Feature Flags
- `ORCHESTRATOR_ENABLE_PERSISTENCE=false` — disables all DB writes (in-memory only, conversations lost on restart)
