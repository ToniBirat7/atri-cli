# E2E Test Results

**Date:** 2026-05-18 → 2026-05-20  
**Branch:** `gemma4-26b`  
**Model:** `gemma-4-26B-A4B-it-UD-Q4_K_M.gguf`  
**Hardware:** RTX 3060 Laptop (6 GB VRAM) + Ryzen 5 6600H + 32 GB RAM

---

## Summary

| Phase | Tests | Result | Notes |
|-------|-------|--------|-------|
| Phase 1 — Unit tests | N/A | **SKIP** | `services/orchestrator/tests/` does not exist; "72 tests" in plan was stale |
| Phase 2 — API layer | A1–A12 | **PARTIAL** | Core routes pass; `/permissions/evaluate` schema mismatch fixed |
| Phase 3 — MCP tools | T1–T13 | **11/13** | T2 timeout (retried), T11 schema error (retried and passed) |
| Phase 4 — Agent loop | L1–L5 | **PARTIAL** | L1/L2/L3 dispatched; L4 skipped (user denied); L5 pending |
| Phase 5 — Prompt profiles | — | **PENDING** | Not yet executed |
| Phase 6 — Thinking mode | — | **PENDING** | Requires .env change + restart |
| Phase 7 — Auth/security | S1,S3,S7 | **PARTIAL** | S1 (anon) pass, S7 (health) pass; multi-command block denied |
| Phase 8 — CLI print mode | — | **PENDING** | Not yet executed |
| Phase 9 — TUI checklist | — | **MANUAL** | Interactive; user must run |
| Phase 10 — Performance | — | **PENDING** | Not yet executed |

---

## Phase 2 — API Layer

| ID | Test | Result |
|----|------|--------|
| A1 | `GET /health` | PASS — `{"status":"ok","llm_connected":true}` |
| A2 | `GET /ready` | PASS — `{"ready":true,...}` |
| A3 | `GET /` | PASS — route list returned |
| A4 | `POST /chat` — "What is 2+2?" | PASS — response contains "4" |
| A5 | `POST /chat/stream` | PASS — SSE stream, ends with `[DONE]` |
| A6 | `GET /tools` | PASS — contains `read_file`, `bash_exec`, etc. |
| A7 | `POST /tools/refresh` | PASS — tool count ≥ 20 |
| A8 | `GET /metrics` | PASS — `uptime > 0` |
| A9 | `POST /permissions/evaluate` | PASS after schema fix (see [[known-issues]]) |
| A10 | `GET /conversations` | PASS — array returned |
| A11 | `POST /chat` `max_turns=1` | PASS — turns ≤ 1 |
| A12 | `GET /mcp/startup-summary` | PASS — startup trace returned |

---

## Phase 3 — MCP Tools

| ID | Tool | Result | Notes |
|----|------|--------|-------|
| T1 | `list_directory` | PASS | Returned project file listing |
| T2 | `read_text_file` | PASS (retry) | Timed out at 120s; passed after timeout patched to 300s |
| T3 | `write_file` | PASS | `/tmp/atri_test.txt` created |
| T4 | `edit_file` | PASS | 'hello world' → 'goodbye world' confirmed |
| T5 | `bash_exec` | PASS | `echo atri_smoke_test` returned correctly |
| T6 | `grep_codebase` | PASS | Found `AgentLoop` in multiple files |
| T7 | `git_status` | PASS | Branch and status returned |
| T8 | `git_log` | PASS | Last 5 commits listed |
| T9 | `directory_tree` | PASS | Tree of `apps/cli/` returned |
| T10 | `search_files` | PASS | Listed all `.py` files in `services/` |
| T11 | `get_file_info` | PASS (retry) | First attempt: model passed `path` (wrong), raised ValueError. Retry with `target_path` passed. |
| T12 | `todo_write`+`todo_read` | PASS (retry) | Timed out at 120s; passed after timeout patched |
| T13 | `get_repo_map` | PASS | Structural summary of 3 directories returned |

---

## Phase 4 — Agent Loop

| ID | Scenario | Result | Notes |
|----|----------|--------|-------|
| L1 | Create + run fibonacci.py | PASS (retry) | File created, bash output with numbers confirmed |
| L2 | Explain TurnOutcome | PASS | Correctly described TOOL_CALLS, NO_TOOL_CALLS, etc. |
| L3 | max_turns=2 enforcement | PASS | Response `turns` field ≤ 2 |
| L4 | Error recovery (nonexistent command) | SKIP | User denied test; would need explicit re-approval |
| L5 | Context retention | PENDING | Two-turn conversation_id test not yet run |

---

## Infrastructure changes made during testing

1. `.env`: `LLM_BASE_URL` patched from `:8000` → `:8080`
2. `.env`: `LLM_TIMEOUT_SECONDS` patched from `120` → `300`
3. `.env`: `PROMPT_POLICY_DEFAULT_PROFILE` set to `agent-v3-26b`
4. Orchestrator restarted once (PID 527211 → 672004) to apply timeout patch

---

## Related pages

- [[known-issues]] — bugs found during testing
- [[llm-inference]] — launch command
- [[mcp-tools]] — tool schemas and gotchas
