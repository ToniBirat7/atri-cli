# Atri Code

A local-first agentic coding CLI powered by **Gemma 4 E2B** via llama.cpp — designed to match Claude Code's capabilities without sending your code to the cloud.

---

> **Next Milestone — Gemma 4 26B A4B MoE**
>
> The next major model upgrade targets [`gemma-4-26B-A4B-it-UD-Q4_K_M.gguf`](https://huggingface.co/) — a 25B-parameter Mixture-of-Experts model with vision support, 16K context window, and llama.cpp-optimized sparse inference (only ~4B parameters active per token). Higher quants (Q6_K / Q8_0) will be the recommended tier for users with 16GB+ VRAM. This upgrade will deliver significantly stronger reasoning and code quality while keeping inference fully local.

---

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ToniBirat7/Agentic_AI/master/install.sh | bash
```

The installer auto-detects your GPU (NVIDIA CUDA / AMD ROCm / Apple Metal / CPU), downloads the matching prebuilt `llama-server`, installs the orchestrator and CLI into `~/.local/share/atri/`, and symlinks the `atri` command into `~/.local/bin/`. The Gemma 4 model (~3.1 GB) is fetched on first run.

**Requirements:** Python 3.10+, Git, `curl`, `unzip`. NVIDIA GPU (4 GB+ VRAM) recommended.

---

## Usage

```bash
# Interactive session (full TUI)
atri

# Single-shot prompt — prints JSON response and exits
atri --prompt "Refactor auth.py to use bcrypt"

# Single-shot with output to stdout only
atri --prompt "List all TODO comments in src/" --print

# System health check + auto-start services
atri doctor

# Stop background services (llama-server + orchestrator)
atri stop
```

---

## How It Works

```
User → atri CLI → FastAPI orchestrator → ReAct agent loop → llama-server (Gemma 4 E2B)
                                              ↓
                                   MCP tool server (filesystem, bash, grep, web search)
```

The orchestrator runs a multi-turn ReAct loop: the model decides which tool to call, the MCP server executes it, results go back to the model, repeat until a final answer is ready. All inference runs locally — nothing leaves your machine.

---

## Developer Setup

```bash
# 1. Clone and install dependencies
git clone https://github.com/ToniBirat7/Agentic_AI.git && cd Agentic_AI
make install

# 2. Configure environment
cp services/orchestrator/.env.example services/orchestrator/.env
# Edit .env: set LLM_API_KEY to match --api-key in the llama-server command

# 3. Start all services (llama + orchestrator + frontend)
make cli-up        # CLI pipeline only (recommended)
# or
make dev-up        # Full stack including Next.js frontend

# 4. Run the CLI
atri

# 5. Run tests
make test
```

### Individual services

```bash
make llama         # Start llama-server on :8000 (foreground)
make orchestrator  # Start FastAPI orchestrator on :8001 (foreground, with --reload)
make frontend      # Start Next.js frontend on :3000

make logs          # Tail llama.log, orchestrator.log, frontend.log
make health        # Curl health checks on all three ports
make dev-down      # Kill all services
make stop          # Kill llama + orchestrator only
```

### Rebuild llama.cpp with CUDA

```bash
make llama-build-gpu    # uses LLAMA_CUDA_ARCH=86 (RTX 30xx); override with:
LLAMA_CUDA_ARCH=89 make llama-build-gpu   # RTX 40xx
```

---

## Project Layout

```
apps/cli/atri_cli/       TUI entry point, service manager, Rich renderer
services/orchestrator/   FastAPI brain — agent loop, LLM adapter, auth, MCP dispatch
services/mcp/            FastMCP tool server — filesystem, bash, grep, todo, web search
runtime/llm/llama.cpp/   llama.cpp build (git submodule)
runtime/state/           SQLite DB, logs, runtime state
models/                  GGUF model files
scripts/                 local_up.py, detect_hardware.py, doctor.py
```

---

## Available MCP Tools

| Tool | What it does |
|---|---|
| `read_text_file` | Read any file within the project root |
| `write_file` | Write or overwrite a file |
| `edit_file` | Exact-string replacement edit (use `exact_text_to_replace`) |
| `list_directory` | List files and dirs at a path |
| `bash_exec` | Run a shell command (sandboxed, with timeout) |
| `grep_codebase` | Regex search across the repo (skips node_modules, .venv, models) |
| `todo_write` / `todo_read` | Persist a task list in `runtime/state/todos.json` |
| `search_web` | Tavily web search (requires `TAVILY_API_KEY`) |

---

## Configuration

All config lives in `services/orchestrator/.env` (copy from `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `LLM_BASE_URL` | `http://127.0.0.1:8000/v1` | llama-server endpoint |
| `LLM_API_KEY` | — | Must match `--api-key` flag on llama-server |
| `AGENT_MAX_TURNS` | `10` | Max ReAct loop iterations per request |
| `AGENT_ENABLE_THINKING` | `false` | Enable Gemma reasoning tokens |
| `ORCHESTRATOR_DATABASE_URL` | `sqlite:///runtime/state/orchestrator.db` | Session store |
| `TAVILY_API_KEY` | — | Required for `search_web` tool |

---

## Uninstall

```bash
~/.local/share/atri/uninstall.sh
```

---

## License

MIT — see [LICENSE](LICENSE).
