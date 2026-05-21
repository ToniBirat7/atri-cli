# Atri Code

**Local-first agentic coding CLI — Claude Code capabilities, running entirely on your GPU.**

Atri Code is a production-grade agentic coding assistant powered by **Gemma 4 E2B** via llama.cpp. It brings the full Claude Code experience (multi-turn ReAct loop, MCP tool execution, file editing, web search, session branching, PLAN mode) without sending a single byte of your code to the cloud.

---

> **Next Milestone — Gemma 4 26B A4B MoE**
>
> The next major model upgrade targets `gemma-4-26B-A4B-it-UD-Q4_K_M.gguf` — a 25B-parameter Mixture-of-Experts model with vision support, 16K context window, and llama.cpp-optimized sparse inference (~4B parameters active per token). Higher quants (Q6_K / Q8_0) will be the recommended tier for users with 16GB+ VRAM.

---

## Features

| Feature | Status |
|---------|--------|
| Multi-turn ReAct agent loop with tool budget controls | Implemented |
| 32 MCP tools — filesystem, bash, git, grep, todo, web search | Implemented |
| PLAN mode — present a plan before executing | Implemented |
| Session tree — fork/branch conversations, append-only JSONL | Implemented |
| Auto-compaction — context distillation at token threshold | Implemented |
| Skills system — user-defined slash commands via SKILL.md | Implemented |
| Model routing — per-request model selection | Implemented |
| Governance hooks — beforeToolCall/afterToolCall interceptors | Implemented |
| Hash-anchored file editing (`hashline.py`) | Implemented |
| Tavily web search | Implemented |
| SSE streaming responses | Implemented |
| JWT + API key auth, admin permission model | Implemented |
| Next.js 15 web UI | Implemented |
| Docker Compose full stack | Implemented |
| Auto-memory mining — extract skills from long sessions | Implemented |
| Tree-sitter code intelligence | In progress |
| PostgreSQL migration tooling | Not started |
| Redis rate limiting | Not started |

---

## Quick Start

```bash
# 1. Clone and install all dependencies
git clone https://github.com/ToniBirat7/Agentic_AI.git && cd Agentic_AI
make install

# 2. Configure environment
cp services/orchestrator/.env.example services/orchestrator/.env
# Edit .env — set LLM_API_KEY=secret (must match --api-key in Makefile)

# 3. Start services and open the TUI
make dev-up
atri
```

Or use the one-command installer (auto-detects GPU, fetches model on first run):

```bash
curl -fsSL https://raw.githubusercontent.com/ToniBirat7/Agentic_AI/master/install.sh | bash
```

---

## Platform Support

| Platform | Support | GPU Backend |
|----------|---------|-------------|
| Linux (Arch, Ubuntu, Fedora) | Full | NVIDIA CUDA / AMD ROCm |
| macOS Apple Silicon | Full | Metal (MPS) |
| macOS Intel | Partial | CPU only (slow) |
| WSL2 (Windows) | Full | NVIDIA CUDA |
| Windows native | Not supported | — |

Baseline dev hardware: AMD Ryzen 5 6600H, NVIDIA RTX 3060 Mobile (6GB VRAM), 32GB RAM, Arch Linux / Hyprland.

---

## Model

| Model | Size | Source |
|-------|------|--------|
| `gemma-4-e2b-it-Q4_K_M.gguf` | ~2.5 GB | [lmstudio-ai/gemma-4-e2b-it-GGUF on HuggingFace](https://huggingface.co/lmstudio-ai/gemma-4-e2b-it-GGUF) |

Place the model file at `models/gemma-4-e2b-it-Q4_K_M.gguf`. The installer fetches it automatically on first run.

**Requirements:** 4GB+ VRAM recommended. CPU-only inference is supported but slow (~5 tok/s on 6-core).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  User                                                               │
│    │  keystroke / --prompt flag                                     │
│    ▼                                                                │
│  atri CLI  (apps/cli/atri_cli/main.py)                             │
│    │  Rich TUI  |  --print mode  |  --permission-mode              │
│    │  ServiceManager: auto-starts llama-server + orchestrator       │
│    │  HTTP POST /chat/stream                                        │
│    ▼                                                                │
│  FastAPI Orchestrator  :8001  (services/orchestrator/api.py)        │
│    │  Auth (JWT / API key)  →  PromptPolicy  →  AgentLoop          │
│    │                                                                │
│    ▼                                                                │
│  AgentLoop  (agent_loop.py)   ─── HookRegistry (hooks.py)          │
│    │  SessionTree (session_tree.py)   Compaction (compaction.py)    │
│    │  MemoryService (memory_service.py)                             │
│    │                                                                │
│    ├─────────────────────────────────────┐                          │
│    ▼                                     ▼                          │
│  llama-server  :8000                  MCP server (in-process)       │
│  Gemma 4 E2B (GGUF)                   32 tools:                    │
│  OpenAI-compat /v1                     filesystem, bash, git,       │
│  Flash Attention, KV quant             grep, todo, web search       │
│                                        diff_engine, repo_map        │
│    │                                                                │
│    ▼                                                                │
│  SSE stream → CLI / Next.js frontend (:3000)                        │
│  SQLite persistence (runtime/state/orchestrator.db)                 │
└─────────────────────────────────────────────────────────────────────┘
```

### Service ports

| Service | Port | Notes |
|---------|------|-------|
| llama-server | 8000 | OpenAI-compat `/v1` endpoint |
| Orchestrator | 8001 | FastAPI, uvicorn, SSE streaming |
| Frontend (Next.js) | 3000 | Optional web UI |

---

## Usage

```bash
# Interactive TUI
atri

# Single-shot prompt — returns JSON and exits
atri --prompt "Refactor auth.py to use bcrypt"

# Single-shot — print raw response to stdout
atri --prompt "List all TODO comments in src/" --print

# Bypass permission prompts (trusted scripts / CI)
atri --permission-mode bypassPermissions --prompt "..."

# System health check + auto-start services
atri doctor

# Stop background services
atri stop
```

### Slash commands (TUI)

| Command | Action |
|---------|--------|
| `/plan` | Switch to PLAN mode — present plan before executing |
| `/fork` | Fork current session to a new branch |
| `/compact` | Manually trigger context compaction |
| `/skills` | List available skills |
| `/<skill-name>` | Invoke a skill by name |
| `/diff` | Show pending diff viewer |
| `/help` | Show all commands |

---

## MCP Tools (32 total)

### Filesystem
`list_directory` · `read_text_file` · `write_file` · `edit_file` · `get_file_info` · `directory_tree` · `search_files`

### Code Search
`grep_codebase` · `get_repo_map`

### Shell
`bash_exec`

### Version Control
`git_status` · `git_log` · `git_diff`

### Task Management
`todo_write` · `todo_read`

### Intelligence / Search
`search_web` (Tavily) + 17 additional tools (intelligence, search adapter, Phase 4-5 additions)

> Full catalog: [.wiki/mcp-tools.md](.wiki/mcp-tools.md)

---

## Developer Setup

```bash
# Start individual services (foreground, with --reload)
make llama          # llama-server on :8000
make orchestrator   # FastAPI on :8001
make frontend       # Next.js on :3000

# Background daemons
make dev-up         # All three services
make cli-up         # CLI pipeline only (no frontend)
make dev-down       # Kill all services

# Utilities
make logs           # Tail llama.log orchestrator.log frontend.log
make health         # curl health checks on all ports
make test           # pytest (services/orchestrator/tests/)

# Rebuild llama.cpp with CUDA
make llama-build-gpu                      # RTX 30xx (arch 86)
LLAMA_CUDA_ARCH=89 make llama-build-gpu  # RTX 40xx
```

---

## Project Layout

```
apps/cli/atri_cli/       TUI entry point, service manager, Rich renderer
apps/frontend/           Next.js 15 web UI with SSE streaming chat
services/orchestrator/   FastAPI brain — agent loop, LLM adapter, auth, MCP dispatch
services/mcp/            FastMCP tool server — 32 tools
runtime/llm/llama.cpp/   llama.cpp build (git submodule)
runtime/state/           SQLite DB, logs, runtime state
models/                  GGUF model files
scripts/                 local_up.py, detect_hardware.py, doctor.py
```

---

## Configuration

All config lives in `services/orchestrator/.env` (copy from `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_BASE_URL` | `http://127.0.0.1:8000/v1` | llama-server endpoint |
| `LLM_API_KEY` | `secret` | Must match `--api-key` on llama-server |
| `LLM_TIMEOUT_SECONDS` | `300` | Use 300+ for large MoE models |
| `AGENT_MAX_TURNS` | `10` | Max ReAct loop iterations per request |
| `AGENT_THINKING_MODE` | `tool_calls_off` | `off` / `tool_calls_off` / `always` |
| `ORCHESTRATOR_DATABASE_URL` | `sqlite:///runtime/state/orchestrator.db` | Session store |
| `TAVILY_API_KEY` | — | Required for `search_web` tool |
| `PROMPT_POLICY_DEFAULT_PROFILE` | `agent-v3-26b` | Prompt profile |

Full reference: [.wiki/configuration.md](.wiki/configuration.md)

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `llm_connected: false` in `/health` | Ensure llama-server runs on port 8000; check `LLM_BASE_URL` |
| Silent empty response from `/chat` | Increase `LLM_TIMEOUT_SECONDS=300` in `.env` |
| `CUDA error: no kernel image` | Wrong CUDA arch; rebuild with correct `LLAMA_CUDA_ARCH` |
| `make install` fails on missing gcc | Install `build-essential` (Ubuntu) or `base-devel` (Arch) |
| Port already in use | `make dev-down` or `lsof -ti tcp:8000 \| xargs kill` |
| Model not found | Place GGUF at `models/gemma-4-e2b-it-Q4_K_M.gguf` |

Full guide: [.wiki/troubleshooting.md](.wiki/troubleshooting.md)

---

## Wiki

- [Installation](.wiki/installation.md) — per-platform setup, GPU variants, gotchas
- [Architecture](.wiki/architecture.md) — full system diagram, event lifecycle
- [MCP Tools](.wiki/mcp-tools.md) — all 32 tools, schemas, gotchas
- [TUI Guide](.wiki/tui.md) — slash commands, PLAN mode, diff viewer, shortcuts
- [Skills](.wiki/skills.md) — user-defined skills, SKILL.md format, discovery
- [Performance](.wiki/performance.md) — llama.cpp flags, KV cache tuning, VRAM tradeoffs
- [Troubleshooting](.wiki/troubleshooting.md) — common errors and fixes
- [Known Issues](.wiki/known-issues.md) — open bugs and workarounds
- [Configuration](.wiki/configuration.md) — all .env variables

---

## Contributing

1. Fork the repo and create a branch from `master`.
2. Follow the dual-import pattern in orchestrator modules (see `.claude/rules/project-architecture.md`).
3. Run `make test` before submitting.
4. Open a PR — describe the change and which phase it belongs to.

---

## Uninstall

```bash
~/.local/share/atri/uninstall.sh
# or manually:
rm -f ~/.local/bin/atri
rm -rf ~/.local/share/atri/
```

---

## License

MIT — see [LICENSE](LICENSE).
