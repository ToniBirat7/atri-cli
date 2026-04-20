# Tarbar AI (CLI Branch)

This branch is the production CLI experience of Tarbar AI: a local-first agent system powered by llama.cpp, orchestrator policy/control loops, and MCP tool calling, delivered through a terminal-native interface.

## What This Project Is

Tarbar AI is an on-device agent architecture for private, controllable AI workflows.

Design goals:
- Keep LLM inference local with llama.cpp
- Execute tools through explicit MCP routes
- Provide auditable agent/tool interactions
- Offer a single-command bootstrap for reproducible setup

## CLI Branch Scope

This `master` branch is optimized for terminal-first usage.

Primary entrypoint:
- `apps/cli` (interactive and print-mode command-line client)

Runtime services:
- `runtime/llm/llama.cpp` (local model inference)
- `services/orchestrator` (agent loop, policies, turn lifecycle, persistence)
- `services/mcp` (tool execution layer)

## Technology Stack

- Inference runtime: llama.cpp
- Orchestration API: Python + FastAPI/Uvicorn
- Tool protocol: MCP (FastMCP)
- CLI client: Python (`apps/cli/tarbar_cli`)
- Build/bootstrap: Bash/PowerShell + Python + CMake
- Persistence: SQLite local state by default

## How the CLI Runtime Works

1. User prompt enters through `tarbar_cli`.
2. CLI sends request to orchestrator (`/chat` or `/chat/stream`).
3. Orchestrator asks llama.cpp for reasoning/action output.
4. If tool calls are required, orchestrator dispatches to MCP.
5. MCP executes tools and returns structured results.
6. Orchestrator loops model + tool outputs until final answer.
7. CLI renders response, timeline, and session metadata.

## CLI Architecture Diagram

```mermaid
flowchart LR
	U[Developer in Terminal] --> C[Tarbar CLI<br/>apps/cli]
	C --> O[Orchestrator API<br/>services/orchestrator]
	O --> L[llama.cpp Server<br/>runtime/llm/llama.cpp]

	O --> M[MCP Service Layer<br/>services/mcp]
	M --> T1[Filesystem Tools]
	M --> T2[Search / Retrieval Tools]
	M --> T3[Custom MCP Adapters]

	O --> D[(SQLite / Postgres<br/>Conversation State)]

	L --> O
	M --> O
	O --> C
```

## MCP and Tool Calls

Tool execution path:
- Model emits a tool request.
- Orchestrator validates policy + permissions.
- Request is routed to MCP tool endpoint(s).
- Tool outputs are normalized and appended to turn context.
- Final answer is returned only after tool-grounded completion.

CLI capabilities include session operations, streaming, permission mode controls, and MCP tool/service inspection.

## One-Command Install and Run

Linux/macOS (CLI mode):

```bash
curl -fsSL https://github.com/ToniBirat7/Agentic_AI/raw/master/scripts/cli_up.sh | bash
```

Windows PowerShell (CLI mode):

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr https://github.com/ToniBirat7/Agentic_AI/raw/master/scripts/cli_up.ps1 -UseBasicParsing | iex"
```

## Local Development

From an existing local clone on this branch:

```bash
make install
make cli-up
```

Run CLI directly:

```bash
cd apps/cli
python -m tarbar_cli.main
```

Print mode example:

```bash
python -m tarbar_cli.main -p "Explain this repository"
```

## Runtime Ports (Default)

- CLI client: local terminal process
- Orchestrator API: `http://127.0.0.1:8001`
- llama.cpp API: `http://127.0.0.1:8000`

## Prerequisites

- Git
- Python 3.10+
- Node.js 20+
- npm
- CMake
- Optional CUDA toolchain (`nvidia-smi`, `nvcc`) for GPU acceleration

## Production Notes

- Branch-aware bootstrap scripts standardize installation and startup.
- Runtime state defaults to durable local persistence.
- Post-start pruning and cache cleanup keep deployment footprints lean.
- Large model binaries remain local and out of version control.

## Branch Strategy

- `master` (this branch): CLI-first workflow.
- `web`: browser-first workflow.

If you need the Web UX, run installers from the `web` branch.
