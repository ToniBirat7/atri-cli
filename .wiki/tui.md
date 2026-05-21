# TUI Guide

Reference for the Atri Code interactive terminal UI, slash commands, PLAN mode, diff viewer, and CLI flags.

---

## Starting the TUI

```bash
atri                          # Interactive TUI (auto-starts services)
atri --prompt "..."           # Single-shot, returns JSON
atri --prompt "..." --print   # Single-shot, prints to stdout only
atri doctor                   # System health check + auto-start services
atri stop                     # Stop background services
```

---

## Slash commands

All commands begin with `/`. Tab-completion is available in the TUI. Type `/help` or `/?` to see the full list inline.

| Command | Description |
|---------|-------------|
| `/help` or `/?` | Show interactive command help |
| `/plan` | Enter PLAN mode — agent explores and plans, no file writes executed |
| `/implement` | Exit PLAN mode and resume normal execution |
| `/fork` | Fork the current session from the latest entry (creates a new branch in the session tree) |
| `/tree` | Print the session conversation tree (shows all branches and turn IDs) |
| `/compact` | Toggle compact output mode (shorter tool results in display) |
| `/model` | List available models |
| `/model <name>` | Set active model for subsequent turns |
| `/cost` | Show session token usage and cost estimate |
| `/clear` | Clear terminal screen |
| `/timeline` | Show current timeline verbosity setting |
| `/timeline <level>` | Set timeline verbosity (`off` / `minimal` / `full`) |
| `/mcp` | Show MCP server status and connected tool list |
| `/skills` | List loaded skills from `~/.atri/skills/` and `.atri/skills/` |
| `/<skill-name>` | Invoke a named skill |
| `/mode` | Show current permission mode |
| `/mode <name>` | Set permission mode (`default` / `bypassPermissions` / `acceptEdits`) |
| `/exit` or `/quit` | Exit interactive mode |

### Tab completion

Slash commands support tab completion. Type `/` and press Tab to see all commands. For `/mode` and `/timeline`, tab-completing after the command shows valid argument values.

---

## PLAN mode

PLAN mode is a read-only exploration mode. When active:

- The agent may read files, search the codebase, and run safe commands.
- **File writes are blocked.** The agent cannot call `write_file`, `edit_file`, or destructive bash commands.
- The agent presents a structured plan (list of proposed changes) and asks for approval before proceeding.

**Workflow:**

```
/plan
> "Refactor the auth module to use bcrypt"

[Agent explores codebase, then presents:]
PLAN:
  1. Replace hashlib.sha256 in auth.py line 42 with bcrypt.hashpw
  2. Add bcrypt to requirements.txt
  3. Update auth tests

Approve this plan? [y/n]
```

After approval, type `/implement` to execute the plan. The agent resumes normal mode and applies the changes.

**Badge:** When PLAN mode is active, `[PLAN]` appears in the input prompt.

---

## Diff viewer

When the agent edits files via `edit_file`, a diff is computed and displayed inline in the TUI before the edit is applied (in `default` permission mode). The diff uses unified diff format with syntax highlighting via Rich.

In `acceptEdits` mode, diffs are applied automatically without prompting. In `bypassPermissions` mode, all tool calls including edits proceed without any confirmation.

Use `/compact` to toggle whether full diff content is shown or summarized.

---

## Session tree and forking

Each conversation is stored as an append-only JSONL tree in `~/.atri/sessions/<session_id>.jsonl`. Every turn is a node with a UUID and a `parent_id` pointer.

**Fork a session:**

```
/fork
```

This creates a new branch from the current turn. The original session is preserved. Use `/tree` to visualize the full branch structure:

```
/tree
Session: a1b2c3d4
  └── [root] user: "Refactor auth.py" (2026-05-21T10:00:00)
        └── [turn-2] assistant: tool_call bash_exec (2026-05-21T10:00:05)
              └── [turn-3] user: "Actually, use bcrypt instead" (2026-05-21T10:01:00)
                    └── [fork-1] ← current branch
```

---

## Permission mode flags

Permission mode controls how the agent handles tool calls that have side effects (file writes, shell commands).

| Mode | Behavior |
|------|---------|
| `default` | Agent prompts before destructive operations (writes, shell) |
| `bypassPermissions` | All tools execute without any confirmation prompt |
| `acceptEdits` | File edits auto-accepted; bash and other operations still prompt |

Set from CLI:

```bash
atri --permission-mode bypassPermissions --prompt "Run full test suite and fix all failures"
```

Set from TUI:

```
/mode bypassPermissions
```

**Note:** `bypassPermissions` requires `is_admin=True` for profile overrides. For local dev, using the CLI flag or the TUI `/mode` command is sufficient.

---

## Keyboard shortcuts

| Shortcut | Action |
|---------|--------|
| `Enter` | Submit message |
| `Tab` | Autocomplete slash command |
| `Ctrl+C` | Cancel current agent turn (sends interrupt) |
| `Ctrl+D` | Exit TUI |
| `Up` / `Down` | Navigate input history |

---

## Single-shot (--print) mode

For scripting and CI use:

```bash
# Returns JSON object with response and turn count
atri --prompt "Summarize the project architecture" --print

# Example output:
{
  "response": "The project consists of...",
  "turns": 3,
  "session_id": "abc123"
}
```

In `--print` mode, the TUI is not rendered. Output goes to stdout. Errors go to stderr.

---

## Service auto-start

When you run `atri` (interactive) or `atri --prompt`, the CLI's `ServiceManager` checks whether llama-server and the orchestrator are running on their expected ports. If not, it starts them automatically as background daemons.

To check service status without starting the TUI:

```bash
atri doctor
make health
```

---

## Related pages

- [[skills]] — defining and invoking skills
- [[agent-loop]] — ReAct loop internals, PLAN mode engine
- [[configuration]] — permission mode and model settings
- [[cli]] — full CLI reference
