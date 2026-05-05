---
paths:
  - "**/*.test.*"
  - "**/*.spec.*"
  - "**/tests/**"
  - "**/test_*.py"
---

# Testing Rules

## Test Runner
pytest 7.4.3 — config at `services/orchestrator/pytest.ini`

## Running Tests
- **All tests:** `cd services/orchestrator && .venv/bin/python -m pytest tests/ -v`
- **Single file:** `cd services/orchestrator && .venv/bin/python -m pytest tests/test_<name>.py -v`
- **Single test:** `cd services/orchestrator && .venv/bin/python -m pytest tests/test_<name>.py::test_<function> -v`
- **Coverage:** `cd services/orchestrator && .venv/bin/python -m pytest tests/ --cov=. --cov-report=html`
- **Via Makefile:** `make test`

## Test Structure
- Test files: `test_*.py` in `services/orchestrator/tests/` (to be created — does not exist yet)
- Test naming: `test_<what>_<condition>` e.g. `test_chat_returns_200_when_authenticated`
- Use `@pytest.mark.asyncio` for async handlers (asyncio_mode=auto in pytest.ini)
- Use `@pytest.mark.unit` vs `@pytest.mark.integration` to classify tests

## Test Markers (from pytest.ini)
- `unit` — isolated, no network/disk
- `integration` — requires full stack
- `native_parsing` — Gemma 4 native tool-call format tests
- `openai_parsing` — OpenAI-format tool-call tests
- `slow` — skip in fast CI with `-m "not slow"`

## What to Test Per Feature
- **New API endpoint:** auth check (401 without key), happy path 200, error case 422/500
- **New MCP tool:** path traversal rejection, happy path, file-not-found error
- **AgentLoop change:** max_turns enforcement, tool budget, early exit on no tool calls
- **LLMAdapter change:** OpenAI format parsing, native Gemma format parsing, retry on 500

## Mocking Patterns
- Mock `LLMAdapter.chat_completion` with `pytest-httpx` to return fixture responses
- Use `OrchestratorDatabase(url=..., enabled=False)` to disable DB in unit tests
- The `pytest-asyncio` `asyncio_mode = auto` means no `@pytest.mark.asyncio` needed per-test
