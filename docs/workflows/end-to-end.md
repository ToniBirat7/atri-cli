# End-to-End Workflow

This document describes the complete request path through Tarbar_AI from the user’s browser to the model and tools and back again.

## Flow Overview

1. The user submits a message in the frontend.
2. The frontend attaches the selected prompt profile and optional allowed filesystem root.
3. The Next.js API route forwards the latest user message to the orchestrator stream endpoint.
4. The orchestrator authenticates the request and checks rate limits.
5. The orchestrator builds the system prompt from the chosen profile.
6. The agent loop sends the prompt and user message to llama.cpp.
7. If the model emits tool calls, the orchestrator resolves them through the MCP registry.
8. The orchestrator executes the tool calls through the MCP service.
9. Tool results are returned to the model for follow-up reasoning.
10. The final answer is streamed back to the frontend.
11. The orchestrator persists the conversation and tool audit trail.
12. Observability data is emitted through structured logs and tracing.

## Services Involved

- Frontend: user interaction and SSE rendering
- Orchestrator: auth, prompt policy, persistence, rate limiting, tracing, and tool routing
- llama.cpp: local model inference
- MCP service: tool execution inside a sandbox
- Postgres: persistent conversation storage
- Redis: distributed rate limiting
- Tempo: trace collection

## Production Readiness Checklist

- JWT authentication enabled for service-to-service traffic
- Prompt policy default selected explicitly
- Redis enabled for rate limiting
- PostgreSQL enabled for persistence
- OTLP endpoint configured for tracing export
- MCP allow-list kept narrow
- Model server health verified before orchestrator start

## Failure Modes

- If llama.cpp is unavailable, the orchestrator should fail health checks and the request should not proceed.
- If MCP tools fail, the agent loop should capture the error and continue only when safe.
- If Redis is unavailable, local rate limiting should remain available.
- If tracing is unavailable, the request path should still function because telemetry is optional.
