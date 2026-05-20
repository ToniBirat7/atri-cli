# CLI (atri)

**Files:**
- `apps/cli/atri_cli/main.py` — entry point, argparse, print mode
- `apps/cli/atri_cli/tui.py` / `rich_tui.py` — Rich-based TUI
- `apps/cli/atri_cli/service_manager.py` — start/stop llama-server + orchestrator
- `apps/cli/atri_cli/client.py` — HTTP client to orchestrator
- `apps/cli/atri_cli/telemetry.py` — local token/cost tracking

## Invocation modes

### Interactive TUI

```bash
atri
```

Full-screen Rich terminal UI. Renders streaming tokens, shows tool calls in timeline, displays tok/s counter.

### Print mode (non-interactive, scriptable)

```bash
atri --print --prompt "Refactor auth.py to use bcrypt"
atri --print --prompt "List files in /tmp" --permission-mode bypassPermissions
atri --print --prompt "Say hello" --output-format json
atri --print --prompt "Complex task" --max-turns 1
```

Returns JSON to stdout. Useful for scripting and CI.

### Other subcommands

```bash
atri doctor      # health check + auto-start services if down
atri stop        # kill llama-server + orchestrator
```

## TUI slash commands

| Command | Effect |
|---------|--------|
| `/help` | Show all commands |
| `/model` | Show current model and hardware info |
| `/cost` | Show token count for current session |
| `/context` | Show context window fill percentage |
| `/thinking on\|off` | Toggle reasoning display |
| `/theme light\|dark` | Switch UI theme |
| `/timeline debug` | Verbose event timeline |
| `/compact` | Summarize + compress conversation history |
| `/resume <N>` | Load session N from `~/.atri/sessions/` |
| `/history` | List past sessions |
| `/export` | Export session as markdown transcript |
| `/diff` | Show current git diff |
| `/clear` | Clear message display |
| `/exit` | Exit TUI (services keep running) |

## Session files

Sessions are persisted to `~/.atri/sessions/`. Each session is a JSON file with conversation history, timestamps, and token counts.

## Service manager

The CLI auto-detects whether llama-server and orchestrator are running. On first launch (or `atri doctor`), it starts them in the background. `atri stop` sends SIGTERM to both.

## Related pages

- [[orchestrator]] — API the CLI calls
- [[architecture]] — how CLI fits into the stack
