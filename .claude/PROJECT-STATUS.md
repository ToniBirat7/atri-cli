# Project Status — 2026-05-05

## Feature Inventory

### ✅ Completed
| Feature | Key Files | Notes |
|---------|-----------|-------|
| CLI TUI (interactive mode) | `apps/cli/atri_cli/main.py` | Rich/prompt_toolkit TUI, `/mode`, `/clear`, `/stop` commands |
| CLI print mode (`--print`) | `apps/cli/atri_cli/main.py` | JSON output, max-turns, permission-mode flags |
| Service Manager (daemon lifecycle) | `apps/cli/atri_cli/service_manager.py` | Auto-start/stop llama-server + uvicorn; sub-second warm reuse |
| Orchestrator FastAPI | `services/orchestrator/api.py` | All routes, startup lifecycle, SSE streaming, metrics |
| Multi-turn ReAct Agent Loop | `services/orchestrator/agent_loop.py` | Budget: max_turns=10, max_tool_calls_per_turn=3 |
| LLM Adapter (llama.cpp) | `services/orchestrator/llm_adapter.py` | OpenAI + native Gemma 4 tool-call parsing, retry logic |
| MCP Filesystem Tools | `services/mcp/main.py` | read_file, write_file, edit_file, list_directory, search_files, directory_tree, get_file_info, create_directory, delete_path, move_file |
| MCP Web Search | `services/mcp/search_adapter.py` | Tavily integration + fetch_url |
| Unified Diff Engine | `services/mcp/diff_engine.py` | `edit_diff` tool for safe patch-style edits |
| MCP Intelligence Server | `services/mcp/intelligence.py` | Tree-sitter code indexing, repo map generation |
| Prompt Policy (profiles) | `services/orchestrator/prompt_policy.py` | `general-purpose`, `legal-strict`, `hybrid`, `agent-v3` |
| JWT + API Key Auth | `services/orchestrator/auth.py` | Hybrid mode, admin API key, anonymous fallback |
| Rate Limiting | `services/orchestrator/redis_rate_limit.py` | In-memory + optional Redis-backed |
| Conversation Persistence | `services/orchestrator/database.py` | SQLite (local), PostgreSQL (Docker), conversation + turns |
| SSE Streaming | `services/orchestrator/api.py` (POST /chat/stream) | Stream events: session_started, assistant_delta, progress, error |
| OpenTelemetry Tracing | `services/orchestrator/tracing.py` | OTLP export to Grafana Tempo |
| Hook Framework | `services/orchestrator/hooks.py` | PreToolUse, PostToolUse, Notification events |
| Git Worktree Support | `services/orchestrator/worktree_manager.py` | Fork conversations to isolated worktrees |
| Settings Overlay System | `services/orchestrator/settings_layer.py` | User/project/local/managed config layering |
| Next.js Web UI | `apps/frontend/src/` | Dark glassmorphism chat UI with SSE streaming |
| Frontend SSE Streaming | `apps/frontend/src/app/api/chat/route.ts` | Proxies orchestrator SSE to browser |
| Workspace Access Control | `apps/frontend/src/components/WorkspaceAccessPanel.tsx` | User-selectable allowed_directory, localStorage persistence |
| Docker Compose Stack | `docker-compose.yml` | llama + orchestrator + frontend + Postgres + Redis + Tempo |
| GPU Build System | `Makefile` (llama-build-gpu) | CUDA cmake build for NVIDIA |
| One-line Installer | `install.sh` | Curl-pipe bootstrap |
| Pre-commit Hooks | `.pre-commit-config.yaml` | Secret scanning, whitespace, merge conflict detection |

### 🚧 In Progress
| Feature | Key Files | Status | Notes |
|---------|-----------|--------|-------|
| V3 Multi-model Support | `atri-cli-v3` branch | Partial | Arena benchmark (50 tasks × N models) removed from master; prompt hardening committed |
| Tree-sitter Code Intelligence | `services/mcp/intelligence.py` | Partially implemented | Deps in requirements.txt; integration with agent loop incomplete |

### 📋 Not Started
| Feature | Priority | Dependencies | Notes |
|---------|----------|--------------|-------|
| Test Suite | High | None | `services/orchestrator/tests/` dir missing; pytest.ini ready |
| PostgreSQL Migration Tooling | Medium | Postgres running | Currently schema is auto-created via `CREATE TABLE IF NOT EXISTS` |
| i18n | Low | None | Fallback/disclaimer text is in Nepali; no formal i18n framework |
| Redis Rate Limiting (live) | Low | Redis running | Code exists but `ORCHESTRATOR_REDIS_ENABLED=false` by default |
| Frontend Error Boundaries | Low | None | No React error boundaries; failures surface as blank UI |
| API Documentation (OpenAPI) | Medium | None | FastAPI auto-generates `/docs` but it's not documented externally |

## Known Issues
- [ ] `AGENT_MAX_TURNS` has a discrepancy: Pydantic field default is 15, but `from_env()` reads `AGENT_MAX_TURNS` defaulting to `"10"` — the env var always wins when set
- [ ] `services/orchestrator/tests/` directory does not exist — `make test` will error with "no tests found"
- [ ] Makefile `_check_model` references `gemma-4-e2b-it-Q4_K_M.gguf` (lowercase) but the E2B model on disk may be `gemma-4-E2B-it-Q4_K_M.gguf` (uppercase E2B) after the download from Unsloth

## Tech Debt
- [ ] Dual import blocks in every orchestrator module are verbose but intentional — do not simplify without testing both invocation modes
- [ ] `api.py` uses module-level globals for singleton objects (`llm_adapter`, `agent_loop`, etc.) — Phase 9 plan is to move these to dependency injection
- [ ] `runtime/llm/llama.cpp/` is a git submodule pinned to a specific commit — keep this in mind when updating llama.cpp

## Branch Summary
| Branch | Purpose | State |
|--------|---------|-------|
| `master` | Production CLI + Web UI | Stable, deployable |
| `web` | Web-first variant with web startup defaults | Synced with master |
| `atri-cli-v3` | V3: multi-model arena, prompt profile hardening | Active dev, partial |
| `v2-development` | V2 archive: diff engine, context amnesia fixes | Archived, merged |
