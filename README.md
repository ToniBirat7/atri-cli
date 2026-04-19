# Tarbar_AI

Tarbar_AI is a local-first agentic AI project that combines:
- llama.cpp runtime for local LLM inference
- MCP servers for tool execution
- a web chat frontend for interaction

## Service Documentation

- [Orchestrator service](docs/services/orchestrator.md) - prompt policy, auth, persistence, rate limiting, and tracing
- [MCP service](docs/services/mcp.md) - filesystem tool execution and sandboxing
- [Frontend service](docs/services/frontend.md) - browser chat experience and API proxying
- [LLM runtime](docs/services/llama.md) - llama.cpp deployment, Jinja prompts, and tool calling
- [End-to-end workflow](docs/workflows/end-to-end.md) - request flow from browser to model to tools and back

## Repository Structure

- `apps/frontend` - Next.js chat application
- `apps/cli` - terminal client for orchestrator-backed chat and session workflows
- `services/mcp` - FastMCP server(s)
- `runtime/llm/llama.cpp` - local llama.cpp runtime source
- `docs` - architecture notes, references, and notebooks
- `models` - local model asset directory (GGUF files are ignored by git)
- `scripts` - helper scripts for local development

## Quick Start

This branch is CLI-focused (Claude Code-style terminal workflow).

Install CLI (Python-first installer):

```bash
curl -fsSL https://raw.githubusercontent.com/ToniBirat7/Agentic_AI/main/install.sh | bash
```

Single-command CLI pipeline:

Linux/macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/ToniBirat7/Agentic_AI/cli/scripts/cli_up.sh | bash
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr https://raw.githubusercontent.com/ToniBirat7/Agentic_AI/cli/scripts/cli_up.ps1 -UseBasicParsing | iex"
```

From an existing local clone:

```bash
make cli-up
```

Branch strategy:
- `master`: complete pipeline for end-to-end local usage on other devices.
- `cli`: this branch, CLI-focused for Claude Code-style terminal workflow.
- `web`: Web-focused branch for Claude Desktop-style browser workflow.

1. Start llama.cpp server from `runtime/llm/llama.cpp` with your selected model.
2. Start MCP server from `services/mcp/main.py`.
3. Start CLI from `apps/cli`:

```bash
cd apps/cli
python -m tarbar_cli.main --help
```

## Notes

- The root `.gitignore` is hardened for production workflows.
- Build artifacts, local caches, logs, and model binaries are excluded from source control.
