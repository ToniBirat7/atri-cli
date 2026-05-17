#!/usr/bin/env python3
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

def print_status(component, status, detail=""):
    color = "\033[92m" if status == "OK" else "\033[91m"
    reset = "\033[0m"
    print(f"[{color}{status}{reset}] {component:20} {detail}")

def check_url(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status == 200, ""
    except Exception as e:
        return False, str(e)

def main():
    repo_root = Path(__file__).resolve().parents[1]
    print(f"Atri Code Doctor - Repo: {repo_root}\n")

    # 1. Check Llama Server
    llama_port = os.environ.get("ATRI_LLAMA_PORT", "8000")
    ok, err = check_url(f"http://127.0.0.1:{llama_port}/health")
    if ok:
        print_status("Llama Server", "OK", f"Port {llama_port}")
    else:
        print_status("Llama Server", "FAIL", f"Port {llama_port} - {err}")

    # 2. Check Orchestrator
    orch_port = os.environ.get("ATRI_ORCH_PORT", "8001")
    ok, err = check_url(f"http://127.0.0.1:{orch_port}/health")
    if ok:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{orch_port}/health") as resp:
                data = json.loads(resp.read().decode())
                print_status("Orchestrator", "OK", f"Version {data.get('status', 'unknown')}")
                
                # Check MCP Servers
                for name, status in data.get("mcp_servers", {}).items():
                    s = "OK" if status.get("status") == "initialized" else "FAIL"
                    print_status(f"  MCP: {name}", s, f"{status.get('tools_discovered', 0)} tools")
        except:
            print_status("Orchestrator", "OK", f"Port {orch_port} (parsed health failed)")
    else:
        print_status("Orchestrator", "FAIL", f"Port {orch_port} - {err}")

    # 3. Check Filesystem + CUDA binary health
    logs = ["llama.log", "orchestrator.log"]
    for log in logs:
        path = repo_root / log
        if path.exists():
            size = path.stat().st_size / 1024
            print_status(f"Log: {log}", "OK", f"{size:.1f} KB")
        else:
            print_status(f"Log: {log}", "MISSING")

    llama_log = repo_root / "llama.log"
    if llama_log.exists():
        log_head = llama_log.read_text(errors="ignore")[:4000]
        if "CUDA0" in log_head or "ggml_cuda" in log_head.lower():
            print_status("CUDA in llama log", "OK", "GPU detected by llama-server")
        elif "CUDA" in log_head:
            print_status("CUDA in llama log", "OK", "CUDA present")
        else:
            print_status("CUDA in llama log", "WARN", "No CUDA found — binary may be CPU-only. Run: make llama-build-gpu")

    # 4. Check Environment
    venv = repo_root / "services/orchestrator/.venv"
    if venv.is_dir():
        print_status("Orchestrator Venv", "OK")
    else:
        print_status("Orchestrator Venv", "FAIL", "Run install.sh")

if __name__ == "__main__":
    main()
