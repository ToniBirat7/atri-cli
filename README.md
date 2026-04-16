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
- `services/mcp` - FastMCP server(s)
- `runtime/llm/llama.cpp` - local llama.cpp runtime source
- `docs` - architecture notes, references, and notebooks
- `models` - local model asset directory (GGUF files are ignored by git)
- `scripts` - helper scripts for local development

## Quick Start

1. Start llama.cpp server from `runtime/llm/llama.cpp` with your selected model.
2. Start MCP server from `services/mcp/main.py`.
3. Start frontend from `apps/frontend`:

```bash
npm install
npm run dev
```

## Notes

- The root `.gitignore` is hardened for production workflows.
- Build artifacts, local caches, logs, and model binaries are excluded from source control.
