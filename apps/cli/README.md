# Tarbar CLI (Increment 1)

Terminal client for Tarbar_AI using the same orchestrator backend as the web app.

## Features in this increment

- Interactive chat loop with SSE streaming
- Print mode (`-p`) for one-off requests
- Session commands: list, resume, fork
- Permission evaluation command for incremental mode/rule testing
- Runtime permission mode via `--permission-mode` and interactive `/mode`
- Protected-path write safety prompts in interactive mode
- MCP server inspection: `mcp tools` and `mcp status` commands
- Shared backend endpoints (`/chat`, `/chat/stream`, `/conversations`, `/conversations/{id}`, `/conversations/{id}/resume`, `/conversations/{id}/fork`, `/tools`, `/health`)

## Run

```bash
cd apps/cli
python -m tarbar_cli.main --help
```

## Install (Python-first, curl | bash bootstrap)

The installer bootstrap is shell-only for startup; all installation logic runs in Python.

```bash
curl -fsSL https://raw.githubusercontent.com/ToniBirat7/Agentic_AI/main/install.sh | bash
```

Optional override for custom installer/archives:

```bash
TARBAR_INSTALLER_URL="https://raw.githubusercontent.com/ToniBirat7/Agentic_AI/main/scripts/install_cli.py" \
TARBAR_INSTALL_ARCHIVE_URL="https://github.com/ToniBirat7/Agentic_AI/archive/refs/heads/main.tar.gz" \
curl -fsSL https://raw.githubusercontent.com/ToniBirat7/Agentic_AI/main/install.sh | bash
```

Examples:

```bash
python -m tarbar_cli.main -p "Explain this project"
python -m tarbar_cli.main -p "Continue this" -r conv_abc123
python -m tarbar_cli.main sessions list
python -m tarbar_cli.main sessions show conv_abc123
python -m tarbar_cli.main sessions fork conv_abc123
python -m tarbar_cli.main permissions check --tool-call "Bash(git push origin main)" --ask "Bash(git push*)"
python -m tarbar_cli.main mcp tools
python -m tarbar_cli.main mcp status
python -m tarbar_cli.main mcp refresh
python -m tarbar_cli.main --permission-mode plan
python -m tarbar_cli.main
```

Interactive helpers:

- `/mode` shows the current permission mode and rule counts
- `/mode <default|plan|dontAsk|bypassPermissions|acceptEdits>` updates mode for the current CLI session

Environment variables:

- `TARBAR_API_URL` (default: `http://127.0.0.1:8001`)
- `TARBAR_API_KEY` (optional API key)
- `TARBAR_ALLOWED_DIRECTORY` (optional workspace root)
- `TARBAR_PERMISSION_MODE` (default permission mode for runtime checks)
