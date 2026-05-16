# Atri Code: Project Context & Objectives

**Goal:** Build a production-grade, local-first agentic coding CLI (`atri-cli`) mirroring Claude Code's capabilities and UX, powered locally via `llama.cpp`.

## Tech Stack

- **Inference:** `llama.cpp` (Full GPU offloading)
- **Backend/Orchestration:** FastAPI
- **Tooling/Protocols:** Model Context Protocol (MCP), Web Search (Tavily)
- **Interfaces:** TUI CLI (`atri-cli`) + Next.js Web UI

## Target Model

- **File:** `gemma-4-26B-A4B-it-UD-Q4_K_M.gguf` + `mmproj-BF16.gguf` (MoE, Text + Vision).
- **Architecture:** 25.2B total params, 3.8B active per token (Mixture-of-Experts: 8 active / 128 total experts).
- **Launch flags:** `--n-gpu-layers 999 --n-cpu-moe 128 --no-mmap --mlock -ctk q4_0 -ctv q8_0 -fa on`
- **Env:** `GGML_CUDA_ENABLE_UNIFIED_MEMORY=1` required on NVIDIA for 6 GB VRAM cards.
- **Implementation Rules:** Strict adherence to Gemma 4 26B MoE inference settings. All llama-server flags must use the MoE-optimized values above. The vision projector (mmproj-BF16.gguf) must be passed via `--mmproj`.

## Core Features & Deliverables

1. **Agentic Capabilities:**
   - Full Claude Code parity (code diffing, file editing, MCP tool execution, Tavily web search).
2. **Premium TUI (`atri-cli`):**
   - High-quality, aesthetic Terminal UI with best-in-class UX.
3. **Smart Installation System:**
   - Single-command cross-platform installer (e.g., `curl -fsSL https://.../install.sh | bash`).
   - **Hardware Auto-Detection:** Dynamically analyzes OS/Device specs to apply optimal `llama.cpp` settings (maximizing GPU utilization for every device).
   - **Self-Cleaning Footprint:** Deletes all build/temporary files post-installation. Only the exact binaries/files needed to run the CLI end-to-end remain on the user's system.

## Baseline Development Hardware

Ensure optimal, 100% GPU-accelerated performance on this baseline, designed to scale dynamically to user devices:

- **OS:** Linux (Omarchy 3.7.1 / Arch-based, Kernel 7.0.3, Wayland/Hyprland)
- **CPU:** AMD Ryzen 5 6600H
- **GPU:** NVIDIA RTX 3060 Mobile (Discrete) + AMD Radeon 660M (Integrated)
- **RAM:** 32GB

## Tech Stack

Python 3.10+ · FastAPI 0.104 · llama.cpp (custom build) · Next.js 15 · React 19 · SQLite (local) / PostgreSQL (Docker) · TailwindCSS 4 · TypeScript 5
Package managers: `pip` (orchestrator venv at `services/orchestrator/.venv`) · `npm` (frontend)
Entry points: `atri` CLI binary · `uvicorn api:app` (orchestrator) · `next dev` (frontend)

## Commands

- `atri`: Launch interactive TUI (requires services running)
- `atri --prompt "..."  --print`: Single-shot mode, returns JSON
- `atri doctor`: System health check + auto-start services
- `atri stop`: Kill background daemons (llama-server + uvicorn)
- `make install`: Install all deps, create venv, symlink `atri` to `~/.local/bin/`
- `make dev-up`: Start llama-server (8000) + orchestrator (8001) + frontend (3000) as background daemons
- `make cli-up`: GPU-autodetect and start CLI-only pipeline (no frontend)
- `make dev-down`: Kill all services
- `make test`: `cd services/orchestrator && .venv/bin/python -m pytest tests/ -v`
- `make health`: curl health checks on all three ports
- `make logs`: Tail `llama.log orchestrator.log frontend.log`
- Single test: `cd services/orchestrator && .venv/bin/python -m pytest tests/test_<name>.py -v`
- `make llama-build-gpu`: Rebuild llama.cpp with CUDA (set `LLAMA_CUDA_ARCH=86` for RTX 3080)
- `docker compose up`: Full production stack with Postgres, Redis, Tempo

## Architecture

- `/apps/cli/atri_cli/` — TUI + service manager; `main.py` is the CLI entry point
- `/services/orchestrator/` — FastAPI brain; agent loop, LLM adapter, prompt policy, auth
- `/services/mcp/` — FastMCP tool server (filesystem, web search, diff engine)
- `/apps/frontend/` — Next.js 15 web UI with SSE streaming chat
- `/runtime/llm/llama.cpp/` — Customized llama.cpp build (git submodule)
- `/runtime/state/` — SQLite DB (`orchestrator.db`), logs, compiled bytecode
- `/models/` — GGUF model files (`gemma-4-26B-A4B-it-UD-Q4_K_M.gguf`, `mmproj-BF16.gguf`)
- `/scripts/` — `local_up.py` (GPU autodetect bootstrap), `doctor.py`, `detect_hardware.py`

## Data Flow

`User` → `CLI/Frontend` → `POST /chat/stream` → `AgentLoop.run()` → `LLMAdapter` → `llama-server:8000` → tool_calls → `MCPOrchestrator.execute_tool()` → `FastMCP (local-mcp)` → filesystem/web → result → LLM → final response → SSE stream back to client

## Key Files

- `services/orchestrator/api.py`: FastAPI app, all routes, startup lifecycle, SSE streaming
- `services/orchestrator/agent_loop.py`: Multi-turn ReAct loop, tool budget controls
- `services/orchestrator/config.py`: All env vars via `OrchestratorConfig.from_env()`
- `services/orchestrator/prompt_policy.py`: Profiles (`general-purpose`, `agent-v3`, `agent-v3-26b`, etc.)
- `services/orchestrator/mcp_orchestrator.py`: MCP server lifecycle, tool dispatch
- `services/mcp/main.py`: All filesystem/search/shell tools (FastMCP)
- `services/mcp/diff_engine.py`: Unified diff applier for code edits
- `apps/cli/atri_cli/service_manager.py`: Auto-start/stop of llama+orchestrator daemons
- `apps/cli/atri_cli/main.py`: CLI argument parsing, TUI rendering, `--prompt`, `--print`, `--permission-mode`
- `apps/frontend/src/app/api/chat/route.ts`: Next.js route that proxies SSE from orchestrator
- `Makefile`: Canonical dev commands — source of truth for all ports and flags

## Environment

- Copy `services/orchestrator/.env.example` → `services/orchestrator/.env`
- `LLM_BASE_URL`: llama-server endpoint (default: `http://127.0.0.1:8000/v1`)
- `LLM_API_KEY`: Must match llama-server `--api-key` flag (default in Makefile: `secret`)
- `AGENT_ENABLE_THINKING`: Set `true` for Gemma reasoning mode (adds `<|think|>` prefix)
- `ORCHESTRATOR_DATABASE_URL`: SQLite for local dev, PostgreSQL in Docker
- `ORCHESTRATOR_JWT_SECRET`: Required in production; optional in local dev (anonymous fallback)
- `NEXT_PUBLIC_API_URL` / `ORCHESTRATOR_URL`: Frontend → orchestrator URL

## Gotchas

- `prompt_profile` override requires `is_admin=True` — only works with `ORCHESTRATOR_ADMIN_API_KEY` or the `--permission-mode bypassPermissions` CLI flag
- llama-server MUST be started with `--jinja` flag for Gemma 4 tool-calling to work
- The `active_model.gguf` symlink pattern was used in benchmark branches — on master, service_manager discovers models directly by filename
- MCP tool `edit_file` requires `exact_text_to_replace`, NOT `old_text`. Wrong key = silent failure
- `services/orchestrator/tests/` does NOT exist yet — tests run from `services/orchestrator/` dir
- Frontend proxies all requests through `/api/chat` → orchestrator; never call orchestrator directly from browser
- `AGENT_MAX_TURNS` default is 10 in `from_env()`, not 15 as shown in the Pydantic field default

## Branches

- `master`: Production CLI + web UI with Gemma 4 E2B; stable baseline
- `gemma4-26b`: **Active development** — Gemma 4 26B A4B MoE model migration (this branch)
- `web`: Web-first variant of master; documents web UI startup defaults
- `atri-cli-v3`: V3 feature development (multi-model arena, prompt profile hardening)
- `v2-development`: Archived V2 work (diff engine, context amnesia fixes); merged to master

## Gotchas (MoE-specific, gemma4-26b branch)

- `--n-cpu-moe 128` is required for Gemma 4 26B — pins all 128 expert layers to CPU RAM
- `--no-mmap` is required for stable MoE inference — do not remove it
- `--mlock` pins model to RAM; may fail without `ulimit -l unlimited` on some Linux configs
- `GGML_CUDA_ENABLE_UNIFIED_MEMORY=1` is set by the launcher for NVIDIA GPUs automatically
- `mmproj-BF16.gguf` must be downloaded alongside the main GGUF; `--mmproj` flag wires it up
- Model search checks `ATRI_MODEL_DIR` env var first, then common paths — set this if model is in a custom location
- `detect_hardware.py` default `model_size_mb` is now 16384 (was 3100 for E2B)
- `PROMPT_POLICY_DEFAULT_PROFILE` defaults to `agent-v3-26b` (not `agent-v3`)

## Current Status

**Completed:** CLI TUI (interactive + print mode), orchestrator API with SSE, MCP filesystem/search/diff tools, JWT + API key auth, SQLite persistence, Docker Compose full stack, frontend Next.js chat UI, `agent-v3-26b` prompt profile (26B MoE-optimized), MoE launch flags, hardware-aware config, harness improvements (syntax highlighting, diff renderer, new tools), risk-tier permission prompt UI, install.sh model prompt redesign (pre-existing model support, path at `user_path/models/` for downloads)
**Not Started:** E2E testing with Gemma 4 26B A4B model, PostgreSQL migration tooling, test suite (`services/orchestrator/tests/` empty), Redis rate limiting integration, i18n

## Compaction Rules

Always preserve: modified file list, failing test output, current task objective, all commands from the Commands section above.
