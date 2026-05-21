# Known Issues

Issues discovered during development and E2E testing. Each entry has a status and workaround.

---

## 1. Port mismatch: llama-server default vs. launch command

**Status:** RESOLVED — canonical port is 8000 everywhere (Makefile, config.py, .env.example, CLAUDE.md)

**Symptom:** Orchestrator fails to connect to LLM; `/ready` returns `llm_connected: false`.

**Root cause:** The codebase default for `LLM_BASE_URL` is `http://127.0.0.1:8000/v1` (in `config.py`, `CLAUDE.md`, and the Makefile). If llama-server was started manually on a different port, the orchestrator cannot reach it.

**Fix:** Ensure llama-server is started on port **8000** (the canonical port). If you started it on a different port, either restart it on 8000 or set `LLM_BASE_URL=http://127.0.0.1:<your-port>/v1` in `services/orchestrator/.env`.

---

## 2. ReadTimeout on 26B model (LLM_TIMEOUT_SECONDS too low)

**Status:** Fixed (one-time .env patch)

**Symptom:** `/chat` returns `{"turns": null, "response": ""}` for requests that require tool use. No error in logs — just silent timeout.

**Root cause:** Default `LLM_TIMEOUT_SECONDS=120` is too short for Gemma 4 26B MoE on hybrid CPU/GPU inference. A single tool-calling turn can take 90–180s including decode.

**Fix:** Set `LLM_TIMEOUT_SECONDS=300` in `services/orchestrator/.env`. Restart orchestrator.

**Note:** Code default in `config.py` is `30`s — even more aggressive. Always override for 26B model.

---

## 3. `get_file_info` field name: `target_path` vs. `path`

**Status:** Open (model behavior, not a code bug)

**Symptom:** `ValueError: Unexpected fields for tool 'get_file_info': path. Valid fields are: target_path`

**Root cause:** The MCP tool schema for `get_file_info` uses `target_path` as the field name. The model frequently hallucinates `path` (the common convention in other tools).

**Workaround:** The agent loop validates fields against the schema before execution. The model will retry on the next turn with corrected fields — but this wastes a turn and can cause timeout on slow hardware. Prompt engineering: tell the model to check tool schemas via `GET /tools` before calling.

---

## 4. `/permissions/evaluate` wrong request schema

**Status:** RESOLVED — schema corrected to `{"tool_call": "<string>", "mode": "default"}`

**Symptom:** 422 Unprocessable Entity when sending `{"tool":"bash_exec","args":{}}`.

**Root cause:** The endpoint expects `{"tool_call": "<string>", "mode": "default"}`, not a structured tool + args object.

**Fix:** Use `{"tool_call": "Bash(echo hello)", "mode": "default"}`.

---

## 5. `--mlock` warning on large model

**Status:** Non-fatal, expected

**Log line:** `warning: failed to mlock 15137390592-byte buffer (Cannot allocate memory)`

**Root cause:** The 26B MoE model requires ~15 GB to mlock. System has 32 GB RAM but not all is free. OS partial-locks what it can.

**Impact:** None on inference correctness. May cause slow performance if pages are swapped, but in practice inference proceeds normally.

---

## 6. Phase 1 unit tests don't exist

**Status:** Open (test directory missing)

**Symptom:** `make test` fails or runs 0 tests. The E2E plan referenced "72 tests" — this is stale documentation.

**Root cause:** `services/orchestrator/tests/` directory was never created (or was deleted). Only `run_tests.py` exists.

---

## 7. `--n-cpu-moe` flag may not be available in all llama.cpp builds

**Status:** Monitor

**Note:** `--n-cpu-moe` is a relatively recent llama.cpp flag for MoE expert routing. If the binary was built before this flag was added, the server will refuse to start. The binary at `runtime/llm/llama.cpp/build/bin/llama-server` supports it (confirmed working in E2E session).

---

## 8. `max_turns` not enforced by agent loop (L3)

**Status:** Open — bug in `agent_loop.py`

**Symptom:** Sending `max_turns=2` in the POST `/chat` body returns `"turns": 99` — the agent runs until it naturally stops instead of being cut off at the requested limit.

**Root cause:** The `max_turns` value from the request body is not being threaded into the agent loop's stop condition. The loop likely reads from config default (`AGENT_MAX_TURNS`) rather than the per-request override.

**Workaround:** Set `AGENT_MAX_TURNS=2` in `.env` and restart orchestrator before testing turn-limited scenarios. Not viable for per-request control.

**Fix target:** `services/orchestrator/agent_loop.py` — locate where `max_turns` is read and ensure the per-request value takes precedence over config default.

---

---

## A.1 New messages bug (TUI rendering)

**Status:** RESOLVED — fixed in Phase 3 TUI rewrite (differential rendering).

---

## A.2 DiffEngine.get_preview() not callable

**Status:** RESOLVED — method renamed and refactored in `services/mcp/diff_engine.py`.

---

## Related pages

- [[llm-inference]] — full launch command and flag rationale
- [[configuration]] — .env variables to patch
- [[mcp-tools]] — `get_file_info` schema
- [[e2e-test-results]] — which tests failed and why
