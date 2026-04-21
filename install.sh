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
import urllib.error
import urllib.request
from pathlib import Path

explicit_installer_url = os.environ.get(
    "ATRI_INSTALLER_URL",
    os.environ.get("TARBAR_INSTALLER_URL"),
)

if explicit_installer_url:
    installer_candidates = [explicit_installer_url]
else:
    installer_candidates = [
        "https://raw.githubusercontent.com/ToniBirat7/Agentic_AI/master/scripts/install_cli.py",
        "https://raw.githubusercontent.com/ToniBirat7/Agentic_AI/main/scripts/install_cli.py",
    ]

with tempfile.TemporaryDirectory(prefix="atri-cli-bootstrap-") as tmp:
    tmp_path = Path(tmp)
    installer_path = tmp_path / "install_cli.py"

    last_error = None
    for installer_url in installer_candidates:
        req = urllib.request.Request(installer_url, headers={"User-Agent": "atri-cli-bootstrap/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                installer_path.write_bytes(response.read())
            break
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code != 404:
                raise
    else:
        if last_error is not None:
            raise last_error
        raise RuntimeError("Unable to download installer from configured URLs")

    runpy.run_path(str(installer_path), run_name="__main__")
PY