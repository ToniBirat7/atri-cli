# Prompt Policy

**Files:**
- `services/orchestrator/prompt_policy.py` — profile lookup, system prompt injection
- `services/orchestrator/config.py` — `PromptPolicyConfig`, `AgentLoopConfig.thinking_mode`

## Prompt profiles

A prompt profile is a named system prompt template. The orchestrator injects it at the start of every conversation.

| Profile | Description |
|---------|-------------|
| `agent-v3-26b` | Optimized for Gemma 4 26B MoE — verbose tool-use instructions, code-focused |
| `agent-v3` | Baseline agent profile |
| `general-purpose` | Default; generic assistant persona |

Default profile is set by `PROMPT_POLICY_DEFAULT_PROFILE` in `.env`. Current live value: `agent-v3-26b`.

### Per-request override

Include `prompt_profile` in the `/chat` request body. **Requires admin API key** (`ORCHESTRATOR_ADMIN_API_KEY`). Without it: 403.

```json
POST /chat
X-API-Key: <admin_key>
{"message": "...", "prompt_profile": "agent-v3-26b"}
```

## Thinking mode

Controlled by `AGENT_THINKING_MODE` in `.env` (or `AgentLoopConfig.thinking_mode`):

| Value | Behavior |
|-------|---------|
| `off` | No reasoning tokens ever |
| `tool_calls_off` | Thinking only on final user-facing turns (not during tool-call turns) |
| `always` | Thinking on every turn (slower, more verbose) |

Current live value: `tool_calls_off`.

To enable thinking for a test: set `AGENT_THINKING_MODE=always` in `.env` and restart orchestrator.

The thinking content appears in the response's `thinking` field (null if not used).

## Fallback / disclaimer text

`PromptPolicyConfig` also holds:
- `fallback_text`: shown when context is missing (Nepali: "मलाई यस बारेमा जानकारी उपलब्ध छैन।")
- `disclaimer_text`: appended to legal/safety responses
- `legal_help_line`: human handoff line for legal-support contexts

These suggest the system was originally built (or extended) for a legal-aid use case in Nepal.

## Related pages

- [[orchestrator]] — how profiles are applied per-request
- [[auth]] — admin key requirement for profile override
- [[configuration]] — AGENT_THINKING_MODE, PROMPT_POLICY_* vars
