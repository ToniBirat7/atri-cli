#!/usr/bin/env bash
set -euo pipefail

INSTALL_URL="${INSTALL_URL:-https://raw.githubusercontent.com/ToniBirat7/Agentic_AI/master/install.sh}"
CMD_NAME="${TARBAR_COMMAND_NAME:-tarbar}"
LOCAL_BIN="${HOME}/.local/bin/${CMD_NAME}"

if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$INSTALL_URL" | bash
elif command -v wget >/dev/null 2>&1; then
  wget -qO- "$INSTALL_URL" | bash
else
  echo "[cli-up] ERROR: curl or wget is required" >&2
  exit 1
fi

if command -v "$CMD_NAME" >/dev/null 2>&1; then
  exec "$CMD_NAME" "$@"
elif [[ -x "$LOCAL_BIN" ]]; then
  exec "$LOCAL_BIN" "$@"
else
  echo "[cli-up] Installed, but launcher not found in PATH." >&2
  echo "[cli-up] Try: export PATH=\"$HOME/.local/bin:\$PATH\"" >&2
  echo "[cli-up] Then run: ${CMD_NAME} $*" >&2
  exit 1
fi
