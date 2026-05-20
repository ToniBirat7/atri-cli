# Overview — Atri Code

## What it is

Atri Code is a **local-first agentic coding CLI** — a self-hosted alternative to Claude Code that runs entirely on your own hardware. No code leaves the machine. The user talks to a terminal UI; the system reasons with a local LLM, calls tools (filesystem, bash, git, search), and iterates until the task is done.

The design goal is to match the capability of cloud coding assistants (Claude Code, GitHub Copilot, Cursor) at zero marginal cost per query, with full privacy.

## Current model

| Property | Value |
|----------|-------|
| Model | Gemma 4 26B A4B MoE (Mixture-of-Experts) |
| Quantization | Q4_K_M GGUF |
| File | `gemma-4-26B-A4B-it-UD-Q4_K_M.gguf` |
| Active params/token | ~4B (MoE sparse activation) |
| Context window | 32 768 tokens |
| Vision | Yes (via `mmproj-BF16.gguf`) |
| Inference backend | llama.cpp (`llama-server`) |
| Dev branch | `gemma4-26b` |

Earlier baseline was **Gemma 4 E2B** (2B dense); the 26B MoE upgrade delivers substantially stronger reasoning.

## Design philosophy

- **Local-first**: all inference on-device, no telemetry to Anthropic/OpenAI/Google
- **ReAct loop**: model decides → tool call → result → decide again, up to `AGENT_MAX_TURNS` (default 10)
- **MCP (Model Context Protocol)**: tools are a separate process/server, not hardcoded into the LLM
- **FastAPI orchestrator**: thin HTTP brain between the CLI and llama-server; handles auth, state, streaming
- **Pluggable prompts**: prompt profiles (agent-v3-26b, general-purpose, etc.) set the system prompt per request

## Repository layout

```
apps/cli/atri_cli/       TUI entry point, service manager, Rich renderer
services/orchestrator/   FastAPI brain — agent loop, LLM adapter, auth, MCP dispatch
services/mcp/            FastMCP tool server — 32 tools
runtime/llm/llama.cpp/   llama.cpp build (git submodule)
runtime/state/           SQLite DB, logs, runtime state (todos.json, orchestrator.db)
models/                  GGUF model files
.wiki/                   This knowledge base
```

## Related pages

- [[architecture]] — full data-flow diagram
- [[llm-inference]] — GPU/CPU hybrid flags for 26B MoE
- [[agent-loop]] — ReAct loop internals
- [[cli]] — user-facing commands
