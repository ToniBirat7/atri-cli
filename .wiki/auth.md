# Authentication & Permissions

**Files:**
- `services/orchestrator/auth.py` — JWT + API key middleware
- `services/orchestrator/permissions.py` — permission evaluation logic

## Auth modes

Set via `ORCHESTRATOR_AUTH_MODE` in `.env`:

| Mode | Behavior |
|------|---------|
| `api-key` | Validates `X-API-Key` header against `ORCHESTRATOR_API_KEY` |
| `jwt` | Validates `Authorization: Bearer <token>` HMAC JWT |
| `hybrid` | Accepts either API key or JWT; falls back to anonymous if neither configured |

If no `ORCHESTRATOR_API_KEY` or `ORCHESTRATOR_JWT_SECRET` is set, all requests are treated as anonymous (unauthenticated access allowed).

## Admin vs. regular key

| Key | Header | Grants |
|-----|--------|--------|
| `ORCHESTRATOR_API_KEY` | `X-API-Key: <value>` | Normal chat, tools, metrics |
| `ORCHESTRATOR_ADMIN_API_KEY` | `X-API-Key: <value>` | All above + `prompt_profile` overrides per request |

Sending `prompt_profile` in a `/chat` request body without the admin key returns **403**.

## Health endpoints

`/health` and `/` are always unauthenticated (controlled by `ORCHESTRATOR_ALLOW_UNAUTHENTICATED_HEALTH=true`).

## Permission evaluation

`POST /permissions/evaluate` — evaluates whether a specific tool call is allowed given the current permission mode.

```json
// Request
{"tool_call": "Bash(rm -rf /tmp/test)", "mode": "default"}

// Response
{"allowed": true|false, "reason": "..."}
```

**Note:** The request body takes `tool_call` (string representation) and `mode`, not `{"tool":"...","args":{}}`. The latter returns 422.

## Permission modes (per-request)

Passed as `permission_mode` in the `/chat` request body:

| Mode | Tools behavior |
|------|---------------|
| `default` | Dangerous operations prompt for confirmation |
| `bypassPermissions` | All tools execute without confirmation |
| `acceptEdits` | File edits auto-accepted; bash prompts |

`bypassPermissions` is used in automated E2E testing. Don't use in production without sandboxing.

## Rate limiting

`ORCHESTRATOR_RATE_LIMIT_PER_MINUTE=0` disables rate limiting. Non-zero values require Redis (`ORCHESTRATOR_REDIS_ENABLED=true`).

## Related pages

- [[orchestrator]] — route definitions
- [[configuration]] — all auth env vars
