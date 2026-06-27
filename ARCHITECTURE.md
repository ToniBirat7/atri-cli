# Atri Code - System Architecture

This document explains how Atri Code works internally, end to end.
It is written against the actual source on the `master` branch, not the aspirational design.
Every claim below maps to a concrete file and function; paths are relative to the repo root.

---

## 1. What Atri Code is

Atri Code is a local-first agentic coding CLI.
It mirrors the Claude Code workflow (read/edit files, run shell, search code, web search, multi-turn tool use) but runs the model locally through `llama.cpp` instead of a hosted API.

The default target model is the text-only Gemma 4 E2B decoder.
The high-capability target is the Gemma 4 26B-A4B MoE (`gemma-4-26B-A4B-it-UD-Q4_K_M.gguf`), selected via `models/` symlink or `ATRI_MODEL_PATH`.

---

## 2. Processes and components

At runtime there are **three OS processes** for the CLI path (a fourth for the web UI):

| Process | What it is | Port | Started by |
|---|---|---|---|
| `llama-server` | `llama.cpp` HTTP inference server, OpenAI-compatible `/v1` API | 8000 | `ServiceManager._start_llama` (`apps/cli/atri_cli/service_manager.py`) |
| `uvicorn api:app` | FastAPI orchestrator - the agent brain | 8001 | `ServiceManager._start_orchestrator` |
| `atri` CLI | Argument parsing + TUI rendering + SSE client | - | user shell |
| `next dev` (web only) | Next.js 15 chat UI, proxies SSE | 3000 | `make dev-up` |

Key architectural fact: **the MCP tool server is NOT a separate process.**
Despite the config string `fastmcp run services/mcp/main.py:mcp`, the orchestrator loads `services/mcp/main.py` as an in-process Python module via `importlib` and calls the `@mcp.tool()` functions directly.
See `MCPOrchestrator._try_load_local_module` and `initialize_server` (`services/orchestrator/mcp_orchestrator.py:323-411`), which sets `mode = "inprocess-module"`.
So tool execution happens inside the orchestrator process, not over stdio/RPC.
The `stdio` transport field exists as a config fallback but the local path is always taken when the command points at `services/mcp/main.py`.

---

## 3. End-to-end: what happens when you prompt through the CLI

Concrete sequence for `atri --prompt "fix the failing test" --print` (interactive TUI follows the same path after input):

1. **CLI parse.** `apps/cli/atri_cli/main.py` parses args, resolves permission mode, builds the request payload (`message`, optional `conversation_id`, `permission_mode`).

2. **Service bootstrap.** `ServiceManager.ensure_running()` checks `http://127.0.0.1:8000/health` (llama) and `:8001/health` (orchestrator).
   If either is down it launches it with `subprocess.Popen` and waits on a health poll (`_wait_for_health`, up to 90s; MoE load is slow).
   Both daemons stay warm across invocations; `atri stop` kills them.

3. **llama-server launch (if needed).** `_start_llama` reads `runtime/llm/launch_config.json` (written by `scripts/detect_hardware.py`) and builds the command:
   `--jinja`, the Gemma 4 tool-use chat template (`runtime/templates/gemma4-tooluse.jinja`), `--ctx-size 32768`, `--cache-type-k q4_0 --cache-type-v q8_0`, `--flash-attn on`, `--no-mmap`, `--parallel 1`, `--api-key secret`, and for MoE: `--n-cpu-moe 999` plus env `GGML_CUDA_ENABLE_UNIFIED_MEMORY=1` and `LD_LIBRARY_PATH` to the build's shared libs.
   `--mlock` is added only if `RLIMIT_MEMLOCK` can hold the model (`_memlock_allows`), otherwise it is skipped because it would silently fail.

4. **HTTP request.** The CLI POSTs the payload to `POST /chat/stream` on the orchestrator and consumes a Server-Sent Events stream (`_print_stream_response` → `client.stream_chat`).

5. **Orchestrator request handling** (`services/orchestrator/api.py:chat_stream`, 1110):
   - `_enforce_runtime_ready_for_chat()` - 503 if MCP not initialized.
   - `_enforce_rate_limit()` - per-client-IP token bucket (Redis or in-memory).
   - `_require_api_key()` + `_authenticate_request()` - JWT or API key; **local dev falls back to anonymous** (`_anonymous_auth_context`).
   - `_resolve_conversation_id()` - reuse the supplied id or mint `conv_<hex>`.

6. **System prompt + history.** `_build_request_system_prompt` selects the profile and builds the system prompt (Section 7).
   `_run_agent_request` loads prior turns for the conversation from SQLite (`build_chat_history_messages`) into `prior_messages`.

7. **Agent loop.** `AgentLoop.run(...)` executes the multi-turn ReAct loop (Section 6), emitting progress events through a callback into an `asyncio.Queue`.

8. **SSE streaming back.** `chat_stream` runs the agent as a background task and drains the progress queue every 150ms, encoding each event as SSE (`stream_event_progress`).
   When the loop finishes, the final answer is chunked (`_chunk_text`, 96 chars) into `assistant_delta` events, then `data: [DONE]`.

9. **Persistence.** `_run_agent_request` calls `conversation_store.record_turn(...)`, writing the turn and its tool calls to SQLite, and (best-effort) mines the session for retained memories.

10. **CLI render.** The TUI renders tool-call cards, streaming tokens, and the final answer.

---

## 4. Inference layer (llama.cpp)

The model is served by `llama-server` exposing `POST /v1/chat/completions`.

Important quirk that shapes everything above it: the served chat format is **peg-native** (verified in `llama.log`: `Chat format: peg-native`), documented at the top of `prompt_policy.py`.
peg-native has two consequences the orchestrator must work around:

- The OpenAI `tools` array is **silently dropped**. Tools must be delivered as text.
- The `tool` message role is **not understood**. Tool results must be delivered as a normal `user` message.

Both workarounds live in `LLMAdapter` (Section 5).

The adapter talks to llama-server over a shared, pooled `httpx.AsyncClient` (`_get_shared_client`, `llm_adapter.py:42`), reused across requests for connection efficiency.

---

## 5. LLM adapter: how messages and tools reach the model

File: `services/orchestrator/llm_adapter.py`.

### 5.1 Request shape (`chat_completion`, 123)
The request body sent to llama-server:
```json
{
  "model": "local-model",
  "messages": [...],
  "temperature": <clamped per turn>,
  "top_p": 0.95, "top_k": 64,
  "max_tokens": 4096,
  "repeat_penalty": 1.1,
  "frequency_penalty": 0.05,
  "extra_body": { "enable_thinking": <bool> }
}
```
`enable_thinking` is passed through `extra_body` so the Gemma 4 Jinja template can inject/suppress `<|think|>` reasoning blocks. The orchestrator never injects `<|think|>` itself.

### 5.2 Tools as text, not JSON param (`_inject_tools_into_system_message`, 640)
When tools are available, their JSON schemas are rendered to text (`build_tool_schema_injection`) and **appended to the system message content** before the request is sent.
This is the peg-native workaround - the structured `tools` field would be dropped.

### 5.3 Tool results as user "Observation" (`format_tool_result`, 623)
A tool result is wrapped as:
```python
{ "role": "user", "content": "Observation from <tool_name>:\n<result>" }
```
Not `role: "tool"`. The model sees results as inline user observations, ReAct-style.

### 5.4 Extracting tool calls (`extract_tool_calls`, 358)
After a completion the adapter looks for `message.tool_calls` first; if absent (common with peg-native), it falls back to parsing the assistant's text content for native/JSON tool-call blocks (`_extract_native_tool_calls`, `_extract_json_block_tool_calls`).
This dual path is why the model can "call a tool" even when the server returns it as plain text.

---

## 6. The agentic loop

File: `services/orchestrator/agent_loop.py`, method `AgentLoop.run` (474).

### 6.1 Initial message stack
```
[ system_prompt,
  *prior_messages (from SQLite for this conversation),
  user_message ]
```
stored in `self.state.messages`.

### 6.2 The turn loop (`while self.state.turn < self.max_turns`)
Default `max_turns = 10` (`config.py` `from_env`; note the Pydantic field default of 15 is overridden).
Each turn:

1. **Budget warning** emitted when one turn remains.
2. **Context trim** (Section 8) if the message list exceeds the window.
3. **Synthesis-turn detection.** If the last message is a tool/user observation and at least one tool already ran, tool schemas are suppressed for this turn (`on_synthesis_turn`) so a small model does not confuse schema text with the answer it must now produce.
4. **LLM call.** Either a streaming final answer (tool-free turns) or `llm_adapter.chat_completion(...)` with tools.
   Tool-call turns clamp temperature to `[temperature_min 0.3, temperature_max 0.6]` for more deterministic JSON.
5. **Usage capture.** `usage` tokens (prompt/completion/total) are recorded per turn and emitted as `usage` SSE events.
6. **Auto-compaction** check (Section 8).
7. **Extract tool calls.** If none:
   - first turn and no tools used yet → may inject a synthetic call or return the direct answer;
   - otherwise → this is the final answer, break.
8. **Cap tool calls** to `max_tool_calls_per_turn` (default 3).
9. **Intent correction** on turn 1 (`_correct_tool_calls_for_intent`).
10. **Execute each tool call** (Section 6.3).
11. After execution, scan results for `Error:` and nudge the model (e.g. "tool not found" correction).

### 6.3 Per-tool execution pipeline
For each requested call (`agent_loop.py:854-1166`):
1. Emit `tool_call_start`.
2. `_validate_tool_input` - normalize field aliases, validate against schema.
3. `resolve_tool_call` - route to `server="local-mcp"` and the real tool name.
4. **Review-mode interception** - if `permission_mode == "review"` and it is an edit, compute a before/after preview and pause for review.
5. **Before-hooks** (`HookRegistry.run_before`) - may block or rewrite input.
6. **Permission gating** (`_tool_requires_confirmation`) - in `default` mode, state-changing tools (edit/delete/etc.) require a confirmation round trip; `acceptEdits` confirms only dangerous ops; `bypassPermissions` confirms nothing.
7. **Tool result cache** - read-only tools (`read_text_file`, `grep_codebase`, `search_web`, ...) are served from an in-memory cache when the same call repeats.
8. **Dispatch** - `mcp_orchestrator.execute_tool(...)` calls the in-process function (Section 6.4).
9. **After-hooks** (`run_after`) - may modify the result.
10. **Distillation** - very large results are spilled to a file with a pointer (Section 8).
11. **Append result** as a user/Observation message; emit `tool_call_result`.
12. Special cases: `propose_plan` and `review` short-circuit and return immediately.

### 6.4 How a tool actually runs (`MCPOrchestrator.execute_tool`, 594)
- Coerce argument types against the discovered JSON schema.
- For in-process mode: `fn = getattr(module, tool_name)`; run with `asyncio.wait_for(..., timeout)`.
- Coroutine tools are awaited; sync tools run in a thread (`asyncio.to_thread`) so they do not block the event loop.
- Retries with backoff up to `max_retries`; dict/list results are JSON-encoded to a string.

### 6.5 Outcome
`run` returns `(final_response, AgentState)`.
`AgentState` carries `total_tool_calls`, `turns_history`, `status`, and the full message list.

---

## 7. The system prompt

File: `services/orchestrator/prompt_policy.py`, `build_system_prompt`.

Profiles (`VALID_PROMPT_PROFILES`): `general-purpose`, `legal-strict`, `hybrid`, `agent-v3`, `agent-v3-26b`, `plan-mode`.

Selection rules:
- The orchestrator launches with `PROMPT_POLICY_DEFAULT_PROFILE`; `service_manager` sets `agent-v3-26b` for MoE models and `agent-v3` otherwise.
- A per-request `prompt_profile` override is honored **only for admin** requests (`is_admin`); anonymous local requests cannot override it.

The two coding profiles differ by model size:
- **`agent-v3`** (E2B, 2.5B): short, blunt, numbered rules - small models need simple direct instructions.
- **`agent-v3-26b`** (26B MoE): richer - explicit tool-selection guidance (when to use `search_symbols` vs `grep_codebase` vs `get_repo_map`), a coding workflow, and the shared `_TOOL_RULES` block.

`_TOOL_RULES` is the critical anti-hallucination contract: never simulate tool output, always use relative paths, `edit_file` takes exactly `target_file_path` / `exact_text_to_replace` / `new_text_content`.

After the profile body the builder appends, when enabled: the hashline-editing DSL section, and a skills snippet (descriptions only) discovered via `skills_loader`.

`plan-mode` is a read-only profile: it permits only read/search/list/web tools and forbids any state-changing tool, ending every response with a numbered `## Plan`.

---

## 8. Context management - the layers that preserve context

There are **seven** distinct context mechanisms, from in-turn to durable:

1. **Working message list** (`AgentState.messages`).
   The live conversation for the current request: system prompt + prior history + user + all assistant/observation messages accumulated across turns.

2. **Context trimming** (`agent_loop.py:547-564`).
   A cheap structural guard for small models. When the list exceeds `context_trim_threshold + 10` (default 40+10=50), it keeps `system[0]`, the original `user[1]`, and the last 40 messages, dropping the middle. No summarization - pure truncation.

3. **Auto-compaction** (`compaction.py`, `should_compact`).
   Token-aware. When `prompt_tokens >= 80%` of context size, the oldest messages are summarized by the LLM into a single `[Context compacted ...]` note; the system prompt, the last 10 messages, and the summary are kept. Triggered mid-loop after the usage event.

4. **Retained-memory injection** (`_inject_retained_memories`).
   After a compaction, durable key/value memories (from the `retain`/`recall` tools, `memory_service`) are re-appended to the system message so they survive summarization.

5. **Tool-result cache** (`_ToolResultCache`, in-memory, 128 entries).
   Deduplicates repeated read-only tool calls within a run; invalidated on writes to the same path.

6. **Context distillation** (`_maybe_distill_result`).
   Oversized tool results are written to a file and replaced in-context with a short pointer ("Full result at: ..."), keyed by turn + tool + call id; the model can re-fetch via `read_tool_result`. Keeps the prompt small without losing data.

7. **Durable persistence** (SQLite, Section 9).
   Across requests, `prior_messages` for a `conversation_id` are reloaded from the database, giving true multi-turn memory beyond a single process call.

So "how many layers of context are preserved": one live in-turn buffer, two in-flight reducers (trim + compaction), two in-flight caches (tool cache + distillation), one memory overlay, and one durable store.

---

## 9. Where conversations are stored

File: `services/orchestrator/database.py`, class `OrchestratorDatabase`.

- **Engine:** SQLite for local dev (`sqlite3`, `check_same_thread=False`, WAL-friendly per-transaction connections). PostgreSQL is supported for the Docker stack via `ORCHESTRATOR_DATABASE_URL`.
- **Location (local):** `runtime/state/orchestrator.db` (absolute path resolved by `local_up._write_orchestrator_env`).
- **Schema (three tables):**
  - `conversations(conversation_id PK, prompt_profile, created_at, ...)`
  - `turns(... conversation_id FK, role/content, usage, created_at ...)`
  - `tool_calls(... linked to turns ...)`
- **Write path:** `ensure_conversation` then `record_turn` after each agent run.
- **Read path:** `build_chat_history_messages(conversation_id, ...)` rebuilds `prior_messages` for the next request.

Persistence can be disabled (`database.enable_persistence`), in which case the agent is stateless across requests.

A parallel, file-based **session tree** (`session_tree.py`, JSONL under `runtime/state/`) records the event timeline per conversation for the TUI's session viewer; it is separate from the relational store.

---

## 10. Tools (the MCP surface)

All tools are defined in `services/mcp/main.py` with `@mcp.tool()` (40 tools), discovered at startup and registered into `ToolRegistry`.

Categories:
- **Filesystem:** `list_directory`, `directory_tree`, `read_text_file`, `read_file`, `read_multiple_files`, `get_file_info`, `create_directory`, `write_file`, `append_file`, `edit_file`, `edit_diff`, `edit_file_hashline`, `move_file`, `delete_path`, `write_json_file`, `create_file`/`create_project`.
- **Sandbox control:** `list_allowed_directories`, `set_allowed_directory(ies)`, `reset_allowed_directories` - every path is checked through `_resolve_path` to enforce the sandbox.
- **Search / code intel:** `search_files`, `grep_codebase`, `search_symbols`, `get_repo_map`, `view_git_diff`.
- **Shell:** `bash_exec` - output capped at 10k lines / 50k chars, 30s default timeout (120s max), with a destructive-command blocklist (e.g. `rm -rf /` returns `Blocked:`).
- **Web:** `search_web`, `fetch_url` - SSRF-guarded (`_assert_public_url` rejects loopback/link-local/metadata IPs).
- **Planning / tasks:** `propose_plan`, `todo_write`, `todo_read`.
- **Memory:** `retain`, `recall`, `list_memories`.
- **Misc:** `server_status`, `read_media_file_base64`, `watch_file`, `stop_watch_file`, `invoke_skill`, `read_tool_result`.

The diff applier behind `edit_diff` lives in `services/mcp/diff_engine.py` (`DiffEngine.apply_diff`).

A second server entry `local-mcp-intelligence` (`services/mcp/intelligence.py`) is configured at startup for code-intelligence tools; it is initialized through the same in-process path.

---

## 11. Startup lifecycle (orchestrator)

`@app.on_event("startup")` (`api.py:885`) wires the singletons, in order:
1. `OrchestratorConfig.from_env()` - single source of truth for all settings.
2. Logging, `HookManager`.
3. `OrchestratorDatabase` + `initialize()` (creates tables).
4. `RequestAuthenticator` (JWT + API key + admin key; mode allows anonymous locally).
5. `DistributedRateLimiter` (Redis or in-memory).
6. Tracing (OTLP optional).
7. `LLMAdapter`, `MCPOrchestrator`, `ToolRegistry`, `AgentLoop`.
8. `ModelRouter` (multi-model support; scans `models/`).
9. **MCP server init:** for each configured server, `initialize_server_with_retry` → `discover_tools(force_refresh=True)` → `register_tools_from_mcp_discovery`. Tool schemas are cached to `runtime/state/mcp_tool_cache.json`.

Per the architecture rules, `api.py` is the only module that instantiates `AgentLoop`/`LLMAdapter`/`MCPOrchestrator`; `agent_loop.py` never imports `api.py`; system prompts are built only in `prompt_policy.py`.

---

## 12. Permission model

Set per request via `permission_mode`:
- `default` - confirm state-changing tools (edits + dangerous ops) before they run.
- `acceptEdits` - auto-accept edits, confirm other dangerous ops.
- `bypassPermissions` - run everything without prompts (benchmarking, trusted scripts); also grants `is_admin`, enabling per-request `prompt_profile` override.
- `review` - intercept edits and return a before/after preview instead of writing.

Confirmation is a real round trip: the loop emits a confirmation request event and awaits the client's decision through a per-conversation queue (`_active_confirmation_queues`).

---

## 13. Configuration and environment

`services/orchestrator/config.py` (`OrchestratorConfig.from_env`) is authoritative. Key knobs:
- `LLM_BASE_URL` (default `http://127.0.0.1:8000/v1`), `LLM_API_KEY` (must match llama-server `--api-key`).
- `max_tokens` 4096, `temperature` 0.6 (clamped to 0.3-0.6 on tool turns), `top_p` 0.95, `top_k` 64.
- `AGENT_MAX_TURNS` 10, `max_tool_calls_per_turn` 3, `context_trim_threshold` 40, compaction threshold 0.80.
- `tool_timeout_seconds` 10, `max_tool_call_retries` 2.
- `AGENT_ENABLE_THINKING`, `PROMPT_POLICY_DEFAULT_PROFILE`, `ORCHESTRATOR_DATABASE_URL`, `ORCHESTRATOR_JWT_SECRET`, `ORCHESTRATOR_ADMIN_API_KEY`.

Device-specific inference settings are not in `.env`; they live in `runtime/llm/launch_config.json`, generated by `scripts/detect_hardware.py` from detected GPU/CPU/RAM.

---

## 14. Data-flow diagram

```
                         ┌─────────────────────────────────────────────┐
  atri CLI / Next.js ───▶│  POST /chat/stream  (FastAPI, :8001)         │
        ▲                │   auth → rate-limit → resolve conversation   │
        │ SSE            │   build system prompt + load prior_messages  │
        │                │                     │                        │
        │                │                     ▼                        │
        │                │              AgentLoop.run()                 │
        │                │   ┌──────────────────────────────────────┐  │
        │  progress      │   │ turn loop (<= max_turns):             │  │
        │  + deltas      │   │  trim/compact context                 │  │
        │◀───────────────┤   │  LLMAdapter.chat_completion ─────────┼──┼──▶ llama-server :8000
        │                │   │   (tools injected as TEXT)           │  │   (Gemma, peg-native)
        │                │   │  extract_tool_calls                  │◀─┼──┐ completion
        │                │   │  for each call:                      │  │  │
        │                │   │    validate→hooks→permission→        │  │  │
        │                │   │    MCPOrchestrator.execute_tool ─────┼──┼──┤ in-process fn call
        │                │   │    append "Observation:" (user role) │  │  │ services/mcp/main.py
        │                │   └──────────────────────────────────────┘  │  │ (40 tools, sandboxed)
        │                │                     │                        │
        │                │                     ▼                        │
        │                │     record_turn → SQLite (runtime/state)     │
        │                └─────────────────────────────────────────────┘
```

---

## 15. Quick reference - file map

| Concern | File |
|---|---|
| CLI entry, TUI, SSE client | `apps/cli/atri_cli/main.py` |
| Service bootstrap (llama + uvicorn) | `apps/cli/atri_cli/service_manager.py` |
| FastAPI app, routes, startup, SSE | `services/orchestrator/api.py` |
| Agentic ReAct loop | `services/orchestrator/agent_loop.py` |
| LLM I/O, peg-native workarounds | `services/orchestrator/llm_adapter.py` |
| In-process MCP dispatch | `services/orchestrator/mcp_orchestrator.py` |
| System prompts / profiles | `services/orchestrator/prompt_policy.py` |
| Context compaction | `services/orchestrator/compaction.py` |
| Persistence (SQLite/Postgres) | `services/orchestrator/database.py` |
| Settings | `services/orchestrator/config.py` |
| Tools (filesystem/web/shell) | `services/mcp/main.py` |
| Diff applier | `services/mcp/diff_engine.py` |
| Inference settings generator | `scripts/detect_hardware.py` → `runtime/llm/launch_config.json` |
