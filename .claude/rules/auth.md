---
paths:
  - "services/orchestrator/auth.py"
  - "services/orchestrator/permissions.py"
  - "apps/cli/atri_cli/main.py"
---

# Auth & Permissions Rules

## Authentication Modes (`ORCHESTRATOR_AUTH_MODE`)
| Mode | Behavior |
|------|----------|
| `hybrid` (default) | Accepts JWT OR API key; anonymous if neither configured |
| `jwt` | JWT only |
| `api-key` | API key only |

## Auth Material Hierarchy
1. If no `jwt_secret`, `api_key`, or `admin_api_key` configured → **anonymous fallback** (no auth enforced)
2. Token extracted from `Authorization: Bearer <token>` OR `x-api-key: <key>` header
3. `ORCHESTRATOR_API_KEY` → regular user (scopes: `chat:read`, `chat:write`)
4. `ORCHESTRATOR_ADMIN_API_KEY` → admin user (can override `prompt_profile`)
5. Valid JWT → decoded for subject/scopes

## Permission Modes (CLI → Orchestrator)
| Mode | Effect |
|------|--------|
| `default` | Agent prompts user for destructive ops |
| `acceptEdits` | Auto-accept file edits, prompt for shell/delete |
| `bypassPermissions` | Skip all permission checks (trusted scripts, benchmarks) |

## CLI Auth Flow
- CLI generates a short-lived JWT from `ORCHESTRATOR_JWT_SECRET` for service-to-service calls
- Token embedded in `Authorization: Bearer` header on every `/chat` request
- `--permission-mode bypassPermissions` is passed as field in the JSON body, not a separate auth mechanism

## Gotchas
- If `ORCHESTRATOR_JWT_SECRET` is not set, auth is fully disabled on the orchestrator — any request succeeds
- `prompt_profile` override is gated on `is_admin=True` — using a regular API key will get a 403
- The `/health` endpoint is always unauthenticated (controlled by `allow_unauthenticated_health=True`)
- The `/permissions/evaluate` endpoint is used by the CLI to check tool permissions before executing — do not remove it
