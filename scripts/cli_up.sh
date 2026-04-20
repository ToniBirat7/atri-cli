#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
BOOTSTRAP_URL="${BOOTSTRAP_URL:-https://raw.githubusercontent.com/ToniBirat7/Agentic_AI/web/scripts/local_up.py}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "[cli-up] ERROR: python3 is required" >&2
  exit 1
fi

if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$BOOTSTRAP_URL" | "$PYTHON_BIN" - --branch web --mode cli "$@"
elif command -v wget >/dev/null 2>&1; then
  wget -qO- "$BOOTSTRAP_URL" | "$PYTHON_BIN" - --branch web --mode cli "$@"
else
  echo "[cli-up] ERROR: curl or wget is required" >&2
  exit 1
fi
