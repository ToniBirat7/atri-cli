# MCP Service

The MCP service provides filesystem and utility tools to the orchestrator through a sandboxed execution boundary. It is the tool execution layer, not the model layer.

## What It Does

The service exposes MCP-compatible tools that can inspect files, list directories, and perform other controlled operations within an allow-listed root. The orchestrator resolves tool calls, applies policy, and then delegates the actual execution to this service.

## Security Model

- Tool access is restricted to an explicit filesystem root
- Destructive or write-capable tools should remain gated or disabled unless needed
- The frontend is the source of the user-selected allow-list root, but the orchestrator should validate and normalize it before use
- The service should never expose the host filesystem without a narrow sandbox

## How It Fits in the Pipeline

1. The LLM asks for a tool call.
2. The orchestrator resolves the tool against the registry.
3. The orchestrator sends the execution request to the MCP server.
4. The MCP server executes the tool within the sandbox.
5. The result is returned to the orchestrator and fed back into the agent loop.

## Documentation Status

The repository already contains service-specific notes in the MCP README. This file exists to give the service a dedicated place in the end-to-end architecture docs and to keep the runtime split explicit.
