# Wiki Log

Append-only record of wiki events. Format: `## [YYYY-MM-DD] <type> | <description>`

---

## [2026-05-20] ingest | Initial wiki creation from codebase + E2E test session

**Sources read:**
- `README.md` — project overview, layout, tool table
- `services/orchestrator/config.py` — full config schema (all env vars, Pydantic models)
- `services/orchestrator/agent_loop.py` — TurnOutcome enum, AgentState, Turn dataclasses, loop structure
- `services/orchestrator/api.py` — route definitions (56 KB, confirmed via file info)
- Prior E2E test session (conversation summary, 2026-05-18/20)

**Pages created:**
- `overview.md` — project summary, current model, design philosophy
- `architecture.md` — full system diagram, service ports, key modules
- `agent-loop.md` — ReAct loop, TurnOutcome state machine, budget controls
- `mcp-tools.md` — 32 tools, schemas, known gotchas
- `orchestrator.md` — FastAPI routes, request lifecycle, SSE format
- `llm-inference.md` — MoE launch command, flag rationale, hardware specs
- `cli.md` — TUI commands, print mode, service manager
- `configuration.md` — all env vars with defaults and notes
- `auth.md` — auth modes, admin key, permission modes
- `prompt-policy.md` — profiles, thinking mode, fallback text
- `e2e-test-results.md` — live test results from 2026-05-18/20 session
- `known-issues.md` — 7 bugs/gotchas with status and workarounds
- `index.md` — catalog of all pages

**Key findings integrated:**
- Port 8080 (not 8000) for llama-server — .env must be patched
- `LLM_TIMEOUT_SECONDS=300` needed for 26B model (default 30/120 too low)
- `get_file_info` field is `target_path` not `path`
- `/permissions/evaluate` takes `{"tool_call": string, "mode": string}`
- No unit test suite exists (tests/ directory missing)
- MoE hybrid: attention on GPU (2.4 GB), expert layers on CPU (14.4 GB)

---

*To add an entry: append a `## [DATE] type | description` block with sources read and pages updated.*
