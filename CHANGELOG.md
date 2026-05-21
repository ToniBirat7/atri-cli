# Changelog

All notable changes to Atri CLI are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] — 2026-05-21

First stable release of Atri CLI — a production-grade, local-first agentic coding CLI
powered by llama.cpp and Gemma 4 E2B, mirroring Claude Code's UX and capabilities.

### Added — Phase E: Advanced Features

- **Idle context compaction (E.2):** Proactively compact conversation context at turn
  boundary when usage exceeds 70%, preventing hard-limit crashes and keeping TTFT low.
  Configurable via `AGENT_IDLE_COMPACT_THRESHOLD_PCT` and `AGENT_IDLE_COMPACT_MIN_TURNS`.
- **MCP tool definition disk cache (E.3):** Cache `listTools()` results to
  `runtime/state/mcp_tool_cache.json` with 1-hour TTL. Falls back to cache on 250ms
  discovery timeout. Configurable via `MCP_TOOL_CACHE_TTL_SECONDS`.
- **Persistent memory tools (E.4):** Three new MCP tools — `retain`, `recall`,
  `list_memories` — store key-value pairs in `~/.atri/memory/` that survive session
  compaction and restarts. Memories are injected into system prompt after every compaction.
- **Confirmation bus (E.5):** Replace blocking tool confirmation with `asyncio.Queue`.
  Agent emits `tool_confirmation_requested` SSE event; CLI responds via new
  `POST /confirm/{session_id}` endpoint. Supports headless/API consumers.

### Added — Phase G: Test Suite & CI

- 102 tests across orchestrator, agent loop, compaction, memory, and MCP modules.
- GitHub Actions CI on push to `master` and all PRs (Python 3.10, 3.11, 3.12).

### Added — Phase E.1: Hash-Anchored Editing

- `edit_file` MCP tool now uses hash-anchored context windows — 61% fewer output tokens
  on typical edits by sending only the changed hunk, not the entire file.

### Added — Phase D: Installation Hardening

- Single-command installer (`install.sh`) with full cross-platform support:
  Linux/macOS, x86_64/arm64, CUDA/ROCm/Metal/CPU auto-detection.
- `atri doctor` command for system health checks with actionable warnings.
- GPU VRAM auto-detection and llama.cpp build flag optimization.
- Self-cleaning install: removes all build artifacts post-install.

### Added — Phase C: Context Distillation

- Large tool results (>4KB) distilled to disk and summarized in-context, preventing
  context window overflow on verbose grep/find outputs.
- `compact_messages()` utility in `compaction.py` for deterministic context compression.

### Added — Phase B: Model Routing & Governance

- Multi-profile prompt system (`prompt_policy.py`): `general-purpose`, `agent-v3`,
  `agent-v3-26b` optimized for Gemma 4 E2B and 26B models.
- Tool budget controls: `AGENT_MAX_TURNS`, `AGENT_MAX_TOOL_CALLS_PER_TURN`.
- JWT + API key auth with admin tier for `prompt_profile` override.

### Added — Phase A: Core Features

- Full agentic ReAct loop (`agent_loop.py`) with multi-turn tool-calling.
- llama.cpp integration via OpenAI-compatible `/v1/chat/completions` endpoint.
- MCP filesystem tools: `read_file`, `write_file`, `edit_file`, `list_directory`,
  `search_files`, `run_shell_command`, `search_web` (Tavily).
- Premium TUI with Rich rendering, diff display, and permission prompts.
- SSE streaming from orchestrator to CLI and Next.js frontend.
- SQLite persistence for conversation history and session state.
- Docker Compose full-stack with PostgreSQL and Redis.

### Fixed — v1.0 Production Hardening

- LLM health-check (`GET /health`) now has 5-second timeout; no longer blocks indefinitely
  if llama-server hangs.
- Memory mining `asyncio.Task` errors now logged at ERROR level instead of silently lost.
- `.env.example` now documents all configurable env vars including auth keys, search
  providers, Redis, and context management settings.

---

## Migration Notes

**From development branches (pre-1.0):**
- Copy `.env.example` → `.env` and fill in any newly documented keys.
- `MCP_TOOL_CACHE_TTL_SECONDS` defaults to 3600 (1 hour) — delete
  `runtime/state/mcp_tool_cache.json` to force fresh discovery on next startup.
- Memory files stored in `~/.atri/memory/` — safe to delete to reset retained memories.
