#!/usr/bin/env python3
"""Atri Code system health check."""
import importlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

# Required packages the orchestrator and MCP server depend on
REQUIRED_PACKAGES = [
    "fastapi",
    "fastmcp",
    "httpx",
    "uvicorn",
    "pydantic",
    "dotenv",
    "structlog",
    "watchdog",
]

MODEL_FILENAME = "gemma-4-e2b-it-Q4_K_M.gguf"
MODEL_MIN_BYTES = 1 * 1024 * 1024 * 1024  # 1 GB


def print_status(component, status, detail=""):
    color = "\033[92m" if status == "OK" else ("\033[93m" if status == "WARN" else "\033[91m")
    reset = "\033[0m"
    print(f"[{color}{status}{reset}] {component:30} {detail}")


def check_url(url, timeout=5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200, ""
    except Exception as e:
        return False, str(e)


def check_gpu_vram():
    """Check GPU VRAM via nvidia-smi; warn if < 4 GB."""
    if shutil.which("nvidia-smi") is None:
        return  # No NVIDIA GPU — skip silently

    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            print_status("GPU VRAM", "WARN", "nvidia-smi failed to query memory")
            return

        for line in result.stdout.strip().splitlines():
            vram_mb = int(line.strip())
            vram_gb = vram_mb / 1024
            if vram_mb < 4096:
                print_status(
                    "GPU VRAM",
                    "WARN",
                    f"{vram_gb:.1f} GB detected — < 4 GB may cause OOM with Gemma 4 E2B",
                )
            else:
                print_status("GPU VRAM", "OK", f"{vram_gb:.1f} GB")
    except (subprocess.TimeoutExpired, ValueError) as e:
        print_status("GPU VRAM", "WARN", f"Could not read VRAM: {e}")


def check_model(repo_root: Path):
    """Check that the model GGUF exists and is larger than 1 GB."""
    # Check canonical dev location first, then install root
    candidates = [
        repo_root / "models" / MODEL_FILENAME,
        Path.home() / ".local/share/atri/models" / MODEL_FILENAME,
    ]
    for model_path in candidates:
        if model_path.exists():
            size = model_path.stat().st_size
            size_gb = size / (1024 ** 3)
            if size < MODEL_MIN_BYTES:
                print_status(
                    "Model file",
                    "WARN",
                    f"{model_path} exists but is only {size_gb:.2f} GB (may be corrupt)",
                )
            else:
                print_status("Model file", "OK", f"{size_gb:.2f} GB — {model_path}")
            return

    print_status(
        "Model file",
        "FAIL",
        f"{MODEL_FILENAME} not found in models/ or ~/.local/share/atri/models/",
    )
    print(
        "       Run: atri  (first-run auto-download)  OR  "
        "install with --skip-model-fetch=false"
    )


def check_packages():
    """Check that required Python packages are importable."""
    for pkg in REQUIRED_PACKAGES:
        try:
            importlib.import_module(pkg)
            print_status(f"  pkg: {pkg}", "OK")
        except ImportError:
            print_status(f"  pkg: {pkg}", "FAIL", "not importable — run: pip install -r requirements.txt")


def attempt_autostart(repo_root: Path):
    """If services are not running, print instructions and optionally auto-start."""
    service_manager = repo_root / "apps/cli/atri_cli/service_manager.py"
    print()
    print("  Services are not running. To start them:")
    if service_manager.exists():
        print("    make dev-up              # background daemons (recommended)")
        print("    make cli-up              # CLI-only mode (no frontend)")
        print(f"    python {service_manager} start  # direct service manager")
    else:
        print("    make dev-up              # background daemons")
        print("    make cli-up              # CLI-only (llama + orchestrator only)")
    print()


def main():
    repo_root = Path(__file__).resolve().parents[1]
    print(f"Atri Code Doctor — Repo: {repo_root}\n")

    services_healthy = True

    # 1. Check Llama Server
    llama_port = os.environ.get("ATRI_LLAMA_PORT", "8000")
    ok, err = check_url(f"http://127.0.0.1:{llama_port}/health")
    if ok:
        print_status("Llama Server", "OK", f"Port {llama_port}")
    else:
        print_status("Llama Server", "FAIL", f"Port {llama_port} — {err}")
        services_healthy = False

    # 2. Check Orchestrator
    orch_port = os.environ.get("ATRI_ORCH_PORT", "8001")
    ok, err = check_url(f"http://127.0.0.1:{orch_port}/health")
    if ok:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{orch_port}/health") as resp:
                data = json.loads(resp.read().decode())
                print_status("Orchestrator", "OK", f"status={data.get('status', 'unknown')}")
                for name, status in data.get("mcp_servers", {}).items():
                    s = "OK" if status.get("status") == "initialized" else "FAIL"
                    print_status(f"  MCP: {name}", s, f"{status.get('tools_discovered', 0)} tools")
        except Exception:
            print_status("Orchestrator", "OK", f"Port {orch_port} (health parse failed)")
    else:
        print_status("Orchestrator", "FAIL", f"Port {orch_port} — {err}")
        services_healthy = False

    # 3. GPU VRAM check
    check_gpu_vram()

    # 4. Model file validation
    check_model(repo_root)

    # 5. Python package dependency audit
    print_status("Python packages", "...", "checking importability")
    check_packages()

    # 6. Filesystem / logs
    for log in ["llama.log", "orchestrator.log"]:
        path = repo_root / log
        if path.exists():
            size_kb = path.stat().st_size / 1024
            print_status(f"Log: {log}", "OK", f"{size_kb:.1f} KB")
        else:
            print_status(f"Log: {log}", "WARN", "not found (services may not have started yet)")

    # 7. Orchestrator venv
    venv = repo_root / "services/orchestrator/.venv"
    if venv.is_dir():
        print_status("Orchestrator Venv", "OK", str(venv))
    else:
        print_status("Orchestrator Venv", "FAIL", "Run: make install  OR  install.sh")

    # 8. Auto-start guidance if services down
    if not services_healthy:
        attempt_autostart(repo_root)

    return 0 if services_healthy else 1


if __name__ == "__main__":
    sys.exit(main())
