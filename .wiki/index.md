# Atri Code — Wiki Index

> LLM-maintained knowledge base. Sources: codebase, README, config files, live E2E test session (2026-05-18/20).
> The LLM owns this layer — read it, don't edit by hand.

---

## Core Concepts

| Page | Summary |
|------|---------|
| [overview.md](overview.md) | What Atri Code is, goals, design philosophy, current model |
| [architecture.md](architecture.md) | Full system diagram — CLI → orchestrator → agent loop → llama-server + MCP |
| [agent-loop.md](agent-loop.md) | ReAct loop internals: TurnOutcome, AgentState, Turn, budget controls |
| [mcp-tools.md](mcp-tools.md) | All 32 MCP tools, schemas, known gotchas (e.g. `target_path` vs `path`) |
| [orchestrator.md](orchestrator.md) | FastAPI service — routes, request lifecycle, streaming, conversation persistence |
| [llm-inference.md](llm-inference.md) | llama-server, Gemma 4 MoE flags, GPU/CPU hybrid strategy, VRAM limits |
| [cli.md](cli.md) | atri CLI — TUI commands, print mode, service manager, session files |
| [configuration.md](configuration.md) | .env variables, OrchestratorConfig schema, all tunables |
| [auth.md](auth.md) | Auth modes (JWT / API key / hybrid), admin key, permission modes |
| [prompt-policy.md](prompt-policy.md) | Prompt profiles, thinking mode, per-request overrides |

## Roadmap & Research

| Page | Summary |
|------|---------|
| [roadmap.md](roadmap.md) | v3 feature roadmap — 5-phase plan derived from Pi + Gemini CLI research |

## Testing & Operations

| Page | Summary |
|------|---------|
| [e2e-test-results.md](e2e-test-results.md) | Live E2E test report — all phases, pass/fail, failures and fixes |
| [known-issues.md](known-issues.md) | Bugs, schema gotchas, timeout tuning, workarounds |

---

*Updated: 2026-05-20 | Sources ingested: README, config.py, agent_loop.py, mcp/main.py, api.py, live E2E session, Pi repo research, Gemini CLI research*
