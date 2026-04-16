## Plan: Local llama.cpp + MCP Agent Harness

Build a Python orchestrator that sits between llama.cpp and one or more MCP servers, using strict tool-schema translation, resilient tool execution, and production observability from day one. Start local-first (single machine, stdio MCP, localhost llama.cpp), then scale to multi-server and remote transports without rewriting the core loop.

**Steps**
1. Phase 1 - Architecture Baseline (blocks all later steps)
Define the core boundaries and contracts: LLM adapter (llama.cpp OpenAI-compatible API), orchestrator runtime, MCP client manager, tool registry, policy/guardrail layer, and observability pipeline.
Confirm first production envelope: localhost-only, API-key-protected llama.cpp, stdio MCP servers, no remote tool transport yet.

2. Phase 2 - Canonical Agent Loop (depends on 1)
Design the deterministic loop: user message -> tool schema set -> model inference -> parse tool_calls -> execute MCP tools -> append tool_result -> continue until end_turn.
Lock protocol choices: non-streamed tool-calling path for reliability (llama.cpp streaming tool extraction is not yet mature), explicit max loop turns, explicit budget guards (time/tokens/tool-calls).

3. Phase 3 - Tool Registry and Schema Discipline (parallel with 2 after interfaces are fixed)
Introduce normalized registry entries: namespaced tool name, server origin, JSON Schema, auth/sensitivity labels, timeout policy, idempotency flag.
Use direct MCP inputSchema passthrough to model tool definitions; avoid lossy translation.
Add selective schema exposure strategy: initial all-tools mode for small catalog, then switch to filtered catalogs as tool count grows.

4. Phase 4 - MCP Client Orchestration Layer (depends on 2 and 3)
Design one client connection per MCP server with lifecycle controls: initialize, capability discovery, health state, reconnect strategy, graceful shutdown.
Define tool routing model: server-prefix namespacing (for collision safety) with stable public aliases.
Handle MCP notifications and catalog refresh events (tools/list_changed) with versioned in-memory snapshots.

5. Phase 5 - Reliability Controls (depends on 2 and 4)
Define robust failure taxonomy and behavior:
- schema/validation errors: fail fast, no blind retries
- transient transport errors/timeouts: bounded retry with jitter
- tool runtime errors: return structured error payload to model
- loop runaway risk: hard caps on turns, tool calls, elapsed time
Specify per-tool timeouts, concurrency limits, backpressure queueing, and circuit-breaker states for unhealthy tools.

6. Phase 6 - Security and Policy Envelope (depends on 4 and 5)
Codify local-first hardening baseline:
- llama.cpp on 127.0.0.1 with API key
- MCP tools run under least-privilege process/user
- explicit allowlist of callable tools
- input/output redaction pipeline for secrets and PII
Define tool risk tiers (read-only, mutating, external-network) with optional user-approval gates for high-impact tools.

7. Phase 7 - Observability and Auditability (parallel with 5 and 6)
Instrument end-to-end traces with correlation IDs per user request and per tool call.
Capture structured logs and metrics: model latency, tool latency, success/failure rates, retries, token usage, cache hit rates, loop depth.
Define minimum dashboards and alerts for local production-like operation.

8. Phase 8 - Testing and Evals Harness (depends on 2 through 7)
Build layered validation:
- unit tests for schema conversion and routing
- integration tests with local llama.cpp + MCP server
- failure-injection tests (timeout, malformed tool args, unavailable server)
- golden conversational scenarios for regression
Add quality gates before expansion of tool catalog.

9. Phase 9 - Scale Path (depends on 8)
Design migration steps without changing orchestrator core:
- add additional MCP servers
- move selected servers from stdio to HTTP/SSE transport
- add model-provider abstraction while keeping llama.cpp optimized path first
- externalize config and secrets management

10. Phase 10 - Incremental Rollout Plan (depends on 9)
Roll out in maturity tiers:
- Tier A: single tool, single server, local only
- Tier B: 5-10 tools, multi-server, policy gates enabled
- Tier C: production baseline with SLO tracking and controlled remote access
Use measurable acceptance criteria before each tier promotion.

**Relevant files**
- /run/media/tonibirat/New Volume/AI_ML_Complete/Agentic_AI/mcp/code/main.py — current MCP server entrypoint and starter tool surface to keep as the first integration target.
- /run/media/tonibirat/New Volume/AI_ML_Complete/Agentic_AI/PLAN.md — repository-level intent statement to align architecture scope and future implementation milestones.
- /run/media/tonibirat/New Volume/AI_ML_Complete/Agentic_AI/resources.md — recommended location to document runtime contracts, operational runbooks, and tool-governance rules.
- /run/media/tonibirat/New Volume/AI_ML_Complete/Agentic_AI/mcp/code/ — recommended directory for orchestrator, adapters, and reliability modules to be added during implementation.

**Verification**
1. Architecture review checklist
Confirm each boundary has explicit interfaces: LLM adapter, MCP routing, policy checks, telemetry hooks, and retry/circuit-breaker semantics.

2. Local deterministic acceptance run
Given a fixed prompt set and fixed tool responses, verify stable tool-selection behavior and deterministic termination conditions.

3. Failure mode drills
Simulate: MCP server down, tool timeout, malformed model tool args, and invalid schema; verify graceful degrade and structured error propagation.

4. Performance and budget baseline
Measure p50/p95 end-to-end latency, per-tool latency, token cost/request, and max loop iterations for representative workloads.

5. Security sanity checks
Validate localhost binding, API key enforcement, blocked high-risk tools by default, and sanitized logging.

**Decisions**
- Orchestrator language: Python.
- Deployment sequence: local single-machine first, with clear scale path.
- Optimization target: llama.cpp-first now, provider abstraction later.
- Tool execution mode: non-streamed tool-calling loop first for reliability.

**Further Considerations**
1. Orchestration framework choice
Recommendation: start with explicit asyncio state machine first; adopt LangGraph only when multi-branch workflows and persistent graph state are needed.

2. Tool exposure strategy as catalog grows
Recommendation: move from full-catalog exposure to policy-driven filtered exposure (intent + user role + risk tier).

3. Approval workflow threshold
Recommendation: require human confirmation for mutating/external side-effect tools from day one, even in local mode.