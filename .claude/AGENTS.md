# Atri Code — Agent Guide

## Project Overview
Atri Code is a local-first agentic coding infrastructure that combines llama.cpp inference with a FastAPI orchestrator and Model Context Protocol (MCP) tools. It serves as a private, self-hosted coding assistant accessible via a terminal TUI (`atri` CLI) and a Next.js 15 web UI. Current state: active development, production-grade V2 on master, V3 multi-model work on `atri-cli-v3` branch.

## Dev Environment Setup
- **Prerequisites:** Python 3.10+, Node.js 20+, CUDA toolkit (for GPU builds), `cmake`, `git`
- **Install:** `make install` — creates venvs, installs all deps, symlinks `atri` to `~/.local/bin/`
- **Run (CLI):** `make cli-up` — GPU autodetect, starts llama-server + orchestrator
- **Run (Full):** `make dev-up` — starts llama-server (8000) + orchestrator (8001) + frontend (3000)
- **Run (Docker):** `docker compose up` — full stack with Postgres, Redis, Grafana Tempo
- **Test:** `cd services/orchestrator && .venv/bin/python -m pytest tests/ -v`
- **Build:** `cd apps/frontend && npm run build`
- **Health:** `make health` or `atri doctor`
- **Stop:** `make dev-down` or `atri stop`

## Tech Stack
- **Backend:** Python 3.10+, FastAPI 0.104, Pydantic v2, uvicorn, httpx
- **LLM Inference:** llama.cpp (custom CUDA build in `runtime/llm/llama.cpp/`), OpenAI-compatible API
- **Models:** Gemma-4-E2B-it-Q4_K_M (2.9GB), Gemma-4-E4B-it-Q4_K_M (4.7GB) in `models/`
- **Tools:** FastMCP, Tavily web search, custom DiffEngine
- **Frontend:** Next.js 15, React 19, TailwindCSS 4, TypeScript 5
- **Database:** SQLite (local), PostgreSQL 16 (Docker)
- **Observability:** OpenTelemetry, Grafana Tempo
- **Auth:** JWT (HS256) + API key, hybrid mode by default

## Project Structure
```
/apps/cli/atri_cli/     CLI entry (main.py) + ServiceManager + TUI renderer
/services/orchestrator/ FastAPI brain: agent loop, LLM adapter, prompt policy, auth
/services/mcp/          FastMCP tool server: filesystem, web search, diff engine
/apps/frontend/         Next.js 15 web UI; proxies SSE from orchestrator
/runtime/llm/llama.cpp/ llama.cpp git submodule (CUDA build)
/runtime/state/         SQLite DB, logs, compiled bytecode (restricted 0700)
/models/                GGUF model files
/scripts/               local_up.py (bootstrap), doctor.py, detect_hardware.py
/deploy/observability/  Grafana Tempo config
/docker-compose.yml     Full production stack definition
/Makefile               All canonical dev commands
```

## Code Conventions
- All orchestrator modules have dual import blocks (`try: from .module import X; except ImportError: from module import X`) to support both package and direct `uvicorn` invocation
- MCP tool calls use `target_file_path` / `target_path` — NEVER `path`, `filepath`, or `src`
- `edit_file` tool MUST use `exact_text_to_replace` — other key names silently fail
- Configuration lives exclusively in `OrchestratorConfig.from_env()` — never hardcode values
- Prompt profiles in `prompt_policy.py` are the source of truth; valid values: `general-purpose`, `legal-strict`, `hybrid`, `agent-v3`
- `agent-v3` profile requires `is_admin=True` OR `--permission-mode bypassPermissions`

## Testing Instructions
- **Unit tests:** `cd services/orchestrator && .venv/bin/python -m pytest tests/ -v` — located in `services/orchestrator/tests/`
- **Single test:** `cd services/orchestrator && .venv/bin/python -m pytest tests/test_<name>.py::test_<function> -v`
- **Coverage:** `cd services/orchestrator && .venv/bin/python -m pytest tests/ --cov=. --cov-report=html`
- Tests must pass before any PR to master
- **Note:** `services/orchestrator/tests/` directory does not yet exist; test suite is a planned feature

## Git Workflow
- **Branch naming:** `feat/*`, `fix/*`, `chore/*`, `docs/*`
- **Commit style:** Conventional commits (`feat:`, `fix:`, `chore:`, `docs:`)
- **Active branches:**
  - `master` — stable production CLI + web UI
  - `web` — web-first variant of master; documents web UI startup defaults
  - `atri-cli-v3` — V3 multi-model arena and prompt hardening (active dev)
  - `v2-development` — archived V2 diff engine / context amnesia work

## Boundaries
- ✅ **Safe to do:** Read files, run tests, run linter, format code, start services with `make`
- ⚠️ **Ask first:** Change `services/orchestrator/config.py` defaults, add new MCP tools, modify `Makefile` ports, change model filenames
- 🚫 **Never do:** Delete `.gguf` model files, commit `services/orchestrator/.env`, rename `active_model.gguf` on master (benchmark artifact), push directly to master, run `make clean` without confirming (deletes `.env`)
