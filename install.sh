#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  if command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    echo "Python 3 is required to install Atri Code CLI." >&2
    exit 1
  fi
fi

"$PYTHON_BIN" - <<'PY'
import os
import runpy
import tempfile
import urllib.request
from pathlib import Path

installer_url = os.environ.get(
    "ATRI_INSTALLER_URL",
    os.environ.get(
        "TARBAR_INSTALLER_URL",
        "https://raw.githubusercontent.com/ToniBirat7/Agentic_AI/main/scripts/install_cli.py",
    ),
)

with tempfile.TemporaryDirectory(prefix="atri-cli-bootstrap-") as tmp:
    tmp_path = Path(tmp)
    installer_path = tmp_path / "install_cli.py"
    req = urllib.request.Request(installer_url, headers={"User-Agent": "atri-cli-bootstrap/1.0"})
    with urllib.request.urlopen(req, timeout=120) as response:
        installer_path.write_bytes(response.read())
    runpy.run_path(str(installer_path), run_name="__main__")
PY