# Claude-Code-Style CLI Clone: Implementation Plan for Tarbar_AI

Date: 2026-04-18
Owner: Tarbar_AI Core Team
Status: Draft for execution

## 1) Goal

Build a Claude-Code-style CLI experience for Tarbar_AI with strong parity on workflow and safety, while keeping one shared backend for both CLI and Web clients.

Primary objective:
- deliver a terminal-first coding agent that uses tool calls for capabilities (filesystem, shell, git, search, MCP tools, memory), with resumable sessions and streaming output.

Non-goal:
- cloning proprietary internals exactly.
- relying on model weights for capabilities that should be implemented as tools.

## 2) Product Principles

1. One backend runtime, many clients
- CLI and Web are thin clients over the same orchestrator APIs, event schema, policy layer, and persistence.

2. Capability through tools
- all actionable capabilities (search, file edits, shell execution, git workflows, MCP integrations) are tool calls, not prompt-only behavior.

3. Safety by default
- deny-first permission model, managed policy overlays, sandboxing for shell, and audit logs.

4. Scale by deferral
- defer large tool schemas and use tool discovery/search so context does not explode as integrations grow.

5. Resumable and automatable
- support interactive sessions plus non-interactive print/json/stream modes for CI and scripts.

## 3) Target Capability Set (Claude-style parity, adapted)

### A. Core CLI UX
- Interactive REPL loop with streaming assistant output
- Non-interactive mode for one-off automation
- Session naming and resume/continue
- Slash command surface for session and tool controls
- Structured output modes: text, json, stream-json

### B. Agent Modes
- default mode: prompt on risky actions
- plan mode: read/analyze only
- accept-edits style mode: auto-approve safe local edits
- bypass mode: highly restricted and policy-gated
- optional auto mode classifier for low-friction operations

### C. Tooling Surface via Tool Call
- file tools: list/read/write/edit/search
- shell tool with sandbox options
- git tools (status, diff, branch, commit, pr helper)
- web search and page fetch tools
- MCP tools (local and remote)
- memory tools (user/session/repo scope)

### D. Team and Scale Features
- project/user/local/managed config scopes
- hooks (pre-tool, post-tool, notification, permission-denied)
- worktree support for parallel sessions
- deferred tool discovery (tool search)
- MCP reconnection and dynamic tool list refresh

### E. Observability and Cost
- per-turn traces and tool telemetry
- token and latency metrics
- budget limits for non-interactive mode
- output truncation and persistence for large tool results

## 4) Architecture Blueprint

## 4.1 Control Plane
- Existing orchestrator remains the source of truth:
  - turn loop
  - tool routing
  - policy enforcement
  - session persistence
  - streaming event broker

## 4.2 Capability Plane
- Tool registry abstraction already present; extend with:
  - search provider adapters
  - fetch/extract tools
  - MCP dynamic discovery endpoint
  - tool metadata annotations (risk, output size, auth)

## 4.3 Policy Plane
- Permission evaluator independent from client:
  - deny > ask > allow precedence
  - mode-based defaults
  - managed policy overlays (future enterprise)
  - optional auto-mode classifier input

## 4.4 Session Plane
- Persistent conversation state:
  - turn history
  - tool call lineage
  - session metadata (name, branch, cwd, model profile)
  - resume and fork semantics

## 4.5 Client Plane
- Web client (already present)
- New CLI client (to build)
- both consume same API contract

## 5) Backend API Contract to Standardize First

Create a versioned conversation protocol used by both clients.

Required endpoints:
1. POST /chat
- request-response mode

2. POST /chat/stream
- SSE stream with typed events

3. GET /conversations
- list recent sessions with metadata

4. GET /conversations/{id}
- full transcript and tool history

5. POST /conversations/{id}/resume
- resume existing session

6. POST /conversations/{id}/fork
- create child session branch

7. GET /tools
- discovered tool catalog (name, source, risk, description)

8. GET /mcp/servers
- MCP health/status and capabilities

9. POST /permissions/evaluate (internal or admin)
- evaluate tool action under mode and rules

10. POST /search/query and POST /search/fetch (internal tool backends)
- provider-neutral retrieval entrypoints

Stream event schema (minimum):
- session_started
- assistant_delta
- assistant_message
- tool_call_requested
- tool_call_started
- tool_call_result
- tool_call_error
- permission_prompt
- permission_decision
- turn_summary
- session_completed

## 6) CLI Design Spec

Binary name:
- tarbar (recommended)

Core commands:
- tarbar
- tarbar "prompt"
- tarbar -p "prompt"
- tarbar -c
- tarbar -r <session-or-name>
- tarbar sessions list
- tarbar sessions rename <id> <name>
- tarbar mcp add/list/get/remove
- tarbar tools list
- tarbar config show

Core flags:
- --print, -p
- --output-format text|json|stream-json
- --permission-mode default|acceptEdits|plan|auto|dontAsk|bypassPermissions
- --session-id <uuid>
- --name <session-name>
- --model <profile>
- --max-turns <n>
- --max-budget-usd <n>
- --allowed-tools <rules>
- --disallowed-tools <rules>
- --add-dir <paths>
- --worktree [name]

In-session slash commands:
- /help
- /clear
- /resume [name]
- /rename <name>
- /tools
- /mcp
- /permissions
- /mode
- /memory
- /status

## 7) Tool-Call Capability Model

Everything actionable should be mapped as a tool with explicit contracts.

Tool categories:
1. Local workspace tools
- list_directory, read_file, write_file, search_files, apply_patch

2. Execution tools
- run_command (sandbox-aware)

3. Version control tools
- git_status, git_diff, git_branch, git_commit, git_log

4. Retrieval tools
- search_web(provider, query, filters)
- fetch_url(url, extract_mode)
- summarize_sources(source_ids)

5. MCP bridge tools
- mcp_call(server, tool, input)
- mcp_list_tools(server)

6. Session/memory tools
- memory_view, memory_create, memory_update

Mandatory metadata per tool:
- risk_level: low|medium|high
- requires_confirmation: boolean
- max_output_tokens
- timeout_seconds
- idempotent: boolean
- allowed_modes

## 8) Search and Retrieval Plan

Provider abstraction:
- SearchProvider interface
  - query(...)
  - normalize_results(...)
  - health(...)

Initial providers:
- Brave (first production provider)
- Tavily (optional second provider / fallback)

Pipeline:
1. query planning
2. provider search
3. fetch top K pages
4. extract and chunk text
5. rank evidence
6. grounded synthesis with citations

Guardrails:
- prompt-injection filtering for fetched content
- citation-required response policy for web-fact questions
- max page count and size limits
- caching by query hash and URL hash

## 9) Permissions, Hooks, and Sandboxing

Permission rule engine:
- precedence: deny > ask > allow
- scope precedence: managed > cli args > local > project > user
- protected path write prompts (for repository safety)

Permission modes:
- default: ask on first risky use
- acceptEdits: auto-approve safe local edits
- plan: no writes, no shell side effects
- auto: classifier assisted approvals (optional phase)
- dontAsk: deny unless explicitly allowed
- bypassPermissions: restricted, disabled by policy by default

Hooks:
- PreToolUse
- PostToolUse
- PermissionDenied
- Notification

Sandboxing:
- shell sandbox for filesystem/network boundaries
- allowlist of domains for networked operations
- deny reads for secrets by default

## 10) MCP Strategy for Scale

Transport support:
- stdio (local)
- http (preferred remote)
- sse (legacy compatibility only)

MCP operational behaviors:
- reconnect with exponential backoff for remote servers
- dynamic refresh on tool list changed notifications
- OAuth and dynamic headers helper support
- configurable output ceilings and persistence for large payloads

Tool Search behavior:
- default deferred loading of tool schemas
- threshold-based mode optional (auto:N)
- load only selected schemas into model context

## 11) Worktrees and Parallel Execution

CLI worktree support:
- tarbar --worktree <name>
- create isolated branch + directory
- session metadata includes worktree id

Subagent/worker isolation:
- optional per-subtask worktree
- cleanup policy:
  - auto-remove when no changes
  - prompt retention when dirty

Repo guidance:
- encourage .claude/worktrees-like ignore path equivalent for Tarbar
- optional .worktreeinclude equivalent for env files

## 12) Implementation Phases

Phase 0: Contract Freeze (1 week)
- finalize stream event schema
- finalize tool metadata schema
- freeze API request/response models

Exit criteria:
- CLI and Web can consume same mocked stream transcript

Phase 1: CLI MVP (2 weeks)
- implement REPL and streaming renderer
- support tarbar, -p, -c, -r, --output-format
- implement /help, /clear, /resume, /tools
- wire to existing orchestrator APIs

Exit criteria:
- user can start, stream, resume, and run tool-backed tasks from CLI

Phase 2: Permission and Mode Engine (2 weeks)
- add mode selector and permission evaluation pipeline
- implement deny/ask/allow rules and settings scopes
- add /permissions and /mode

Exit criteria:
- deterministic permission decisions with audit logs

Phase 3: Search Capability (2 weeks)
- add search_web and fetch_url tools
- provider abstraction + Brave integration
- citation enforcement policy for web answers
- caching and output-size controls

Exit criteria:
- CLI and Web can answer fresh web questions with source citations

Phase 4: MCP Scale Features (2 weeks)
- add MCP server lifecycle commands in CLI
- add reconnection + dynamic tool refresh
- add deferred tool discovery path

Exit criteria:
- large tool catalogs do not bloat startup context

Phase 5: Worktrees + Parallel Sessions (1-2 weeks)
- --worktree support in CLI
- session branch/fork support
- cleanup logic and safety prompts

Exit criteria:
- user can run independent parallel tasks safely

Phase 6: Hardening and Enterprise Controls (2 weeks)
- managed settings layer
- hook framework and policy gates
- structured observability and cost controls

Exit criteria:
- production-ready reliability and governance posture

## 13) File-by-File Delivery Plan (Current Repo)

Backend (services/orchestrator):
- api.py
  - add/standardize session and stream endpoints
- agent_loop.py
  - enforce tool metadata constraints and mode constraints
- tool_registry.py
  - add category/risk metadata and deferred schema support
- mcp_orchestrator.py
  - add reconnection state and dynamic capability refresh hooks
- prompt_policy.py
  - split mode-specific prompt segments
- new: permissions.py
  - rule engine + mode resolution
- new: search_adapter.py
  - provider abstraction + normalization
- new: search_tools.py
  - search_web/fetch_url tool execution

CLI app (new top-level app suggested):
- apps/cli/pyproject.toml
- apps/cli/tarbar_cli/main.py
- apps/cli/tarbar_cli/repl.py
- apps/cli/tarbar_cli/stream_renderer.py
- apps/cli/tarbar_cli/commands.py
- apps/cli/tarbar_cli/session_store.py
- apps/cli/tarbar_cli/config.py

Docs and runbooks:
- docs/cli/overview.md
- docs/cli/commands.md
- docs/security/permissions.md
- docs/security/sandboxing.md
- docs/mcp/operations.md

## 14) Testing Strategy

Unit tests:
- permission rule matching and precedence
- mode transitions
- tool metadata validation
- search provider normalization

Integration tests:
- CLI to backend streaming contract
- resume/fork flows
- permission prompts under each mode
- search + citation output
- MCP reconnect behavior

E2E tests:
- "fix bug" workflow in CLI
- "plan then implement" workflow
- worktree parallel workflow
- non-interactive CI usage with json output

Performance tests:
- startup latency with 10/50/200 tools
- context size impact with deferred tool schemas
- streaming responsiveness under long tool calls

## 15) Metrics and Success Criteria

Adoption metrics:
- percent of sessions started in CLI
- average resumed-session rate
- percent of tasks completed without UI handoff

Quality metrics:
- tool call success rate
- permission false-positive prompt rate
- web answer citation coverage
- escaped policy violation rate (target near zero)

Performance metrics:
- time to first token
- median turn latency
- stream interruption rate
- memory/context utilization over long sessions

## 16) Risks and Mitigations

1. CLI/Web behavior drift
- Mitigation: one backend protocol, shared tests for both clients

2. Context blow-up with many tools
- Mitigation: deferred tool discovery and schema paging

3. Prompt injection via web/MCP outputs
- Mitigation: untrusted-content channel, sanitizer, strict policy boundaries

4. Unsafe shell actions
- Mitigation: deny-first rules + sandbox + protected path prompts

5. Provider lock-in for search
- Mitigation: provider abstraction and fallback support

## 17) Immediate Next 10 Engineering Tasks

1. Freeze unified stream event schema in orchestrator docs.
2. Create CLI skeleton under apps/cli with Typer + Rich.
3. Implement chat stream client and renderer in CLI.
4. Add session list/resume/fork backend endpoints.
5. Add permission engine module and mode resolver.
6. Add --permission-mode and /mode in CLI.
7. Add search provider interface and Brave adapter.
8. Register search_web and fetch_url tools in tool registry.
9. Add citation-required output policy for web-grounded answers.
10. Add integration tests for CLI stream + permission + search path.

## 18) Recommendation

Proceed with Phase 0 immediately and lock the shared protocol before adding features. This is the critical decision that keeps the CLI clone scalable and prevents a second, divergent runtime.

Once protocol freeze is done, build CLI MVP and search tools in parallel tracks, then converge on permission/mode hardening before wider rollout.
