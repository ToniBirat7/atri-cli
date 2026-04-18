# Tarbar Claude-Style CLI/Web Shared Backend Checklist

Status legend:
- [x] done
- [~] in progress
- [ ] pending

## Increment 1: Shared session API + CLI foundation

- [x] Add conversation detail endpoint (`GET /conversations/{id}`)
- [x] Add conversation resume endpoint (`POST /conversations/{id}/resume`)
- [x] Add conversation fork endpoint (`POST /conversations/{id}/fork`)
- [x] Include `conversation_id` in stream metadata events
- [x] Load prior conversation messages into agent loop for continuation
- [x] Create `apps/cli` scaffold
- [x] Implement CLI interactive mode
- [x] Implement CLI print mode (`-p`)
- [x] Implement CLI session commands (`list/show/resume/fork`)
- [x] Add CLI automated tests

## Installer: Python-first distribution

- [x] Add Python installer script (`scripts/install_cli.py`)
- [x] Add curl|bash bootstrap (`install.sh`) that only launches Python installer
- [x] Document public install command in CLI and root docs
- [x] Add installer test for local repo installation path

## Increment 2: Mode + permissions parity

- [x] Add backend permission evaluation endpoint contract
- [ ] Implement CLI `--permission-mode` and `/mode`
- [x] Add CLI `/permissions` helper command
- [ ] Implement protected-path write prompts in CLI renderer
- [x] Add deterministic tests for deny > ask > allow behavior

## Increment 3: Search capability via tool calls

- [ ] Add provider abstraction (`search_adapter.py`)
- [ ] Implement `search_web` tool
- [ ] Implement `fetch_url` tool
- [ ] Add citation-enforcement prompt policy for web-grounded answers
- [ ] Add integration tests for search grounding

## Increment 4: MCP scaling features

- [ ] Add MCP status/list commands in CLI
- [ ] Add dynamic tool list refresh support
- [ ] Add reconnection/backoff handling for remote MCP servers
- [ ] Add deferred tool discovery toggle and thresholds

## Increment 5: Worktrees and parallel flows

- [ ] Add CLI `--worktree` support
- [ ] Add conversation fork-to-worktree workflow helper
- [ ] Add cleanup and safety prompts for dirty worktrees

## Increment 6: Observability and hardening

- [ ] Add per-turn CLI telemetry summaries (latency, tool count)
- [ ] Add stream-json output mode for CI pipelines
- [ ] Add budget controls in CLI (`--max-turns`, `--max-budget-usd`)
- [ ] Add security-focused regression tests (prompt injection, dangerous shell)
