#!/usr/bin/env python3
"""
Atri-Arena v3 — Proper Benchmark Runner
=========================================
50 unique tasks × 4 models = 200 evaluations.
Each task resets Project Nebula via git, captures JSON telemetry,
and validates results with specific per-task checks.
"""

import json
import subprocess
import time
import os
from pathlib import Path
from datetime import datetime

# --- CONFIGURATION ---
MODELS = [
    {"name": "Gemma-4-e2b",       "file": "gemma-4-e2b-it-Q4_K_M.gguf"},
    {"name": "Gemma-4-E4B",       "file": "gemma-4-E4B-it-Q4_K_M.gguf"},
    {"name": "Llama-3.2-3B",      "file": "llama-3.2-3b-instruct-q4_k_m.gguf"},
    {"name": "Qwen-2.5-Coder-3B", "file": "qwen2.5-coder-3b-instruct-q5_k_m.gguf"},
]

PROJECT_ROOT    = Path("/run/media/tonibirat/New Volume/AI_ML_Complete/Agentic_AI")
NEBULA_ROOT     = PROJECT_ROOT / "benchmarks/v3_arena/project_nebula"
RESULTS_DIR     = PROJECT_ROOT / "benchmarks/v3_arena/results"
TASK_FILE       = PROJECT_ROOT / "benchmarks/v3_arena/tasks/tasks.json"
ATRI_BIN        = "/home/tonibirat/.local/bin/atri"
CANONICAL_MODEL = "gemma-4-e2b-it-Q4_K_M.gguf"
MODELS_DIR      = PROJECT_ROOT / "models"
TASK_TIMEOUT    = 120  # 2 minutes per task


def stop_services():
    """Stop all atri services cleanly."""
    print("  [SVC] Stopping services...")
    subprocess.run([ATRI_BIN, "stop"], capture_output=True, timeout=30)
    time.sleep(2)
    subprocess.run(["pkill", "-9", "-f", "llama-server"], capture_output=True)
    subprocess.run(["pkill", "-9", "-f", "uvicorn.*api:app"], capture_output=True)
    time.sleep(3)


def wait_for_services(timeout=120):
    """Wait for both llama-server and orchestrator to be healthy."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            for url in ["http://127.0.0.1:8000/health", "http://127.0.0.1:8001/health"]:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=2):
                    pass
            return True
        except Exception:
            time.sleep(1)
    return False


def swap_model(model_filename: str):
    """Swap the active model by renaming files."""
    canonical = MODELS_DIR / CANONICAL_MODEL
    target    = MODELS_DIR / model_filename
    backup    = MODELS_DIR / f"_bak_{CANONICAL_MODEL}"

    if model_filename == CANONICAL_MODEL:
        return

    if canonical.exists():
        canonical.rename(backup)
    if target.exists():
        target.rename(canonical)
    print(f"  [SWAP] Activated {model_filename}")


def restore_model(model_filename: str):
    """Restore original model names."""
    canonical = MODELS_DIR / CANONICAL_MODEL
    target    = MODELS_DIR / model_filename
    backup    = MODELS_DIR / f"_bak_{CANONICAL_MODEL}"

    if model_filename == CANONICAL_MODEL:
        return

    if canonical.exists():
        canonical.rename(target)
    if backup.exists():
        backup.rename(canonical)
    print(f"  [SWAP] Restored original names")


def reset_nebula():
    """Reset Project Nebula to pristine state using git."""
    subprocess.run(
        ["git", "checkout", "--", "benchmarks/v3_arena/project_nebula/"],
        cwd=str(PROJECT_ROOT), capture_output=True
    )
    # Clean untracked files created by the agent
    subprocess.run(
        ["git", "clean", "-fd", "benchmarks/v3_arena/project_nebula/"],
        cwd=str(PROJECT_ROOT), capture_output=True
    )


def run_task(task: dict) -> dict:
    """Run a single task and capture JSON telemetry."""
    start = time.time()

    try:
        result = subprocess.run(
            [
                ATRI_BIN,
                "--prompt", task["prompt"],
                "--permission-mode", "bypassPermissions",
                "--print",
                "--max-turns", "10",
                "--output-format", "json",
            ],
            cwd=str(NEBULA_ROOT),
            capture_output=True,
            text=True,
            timeout=TASK_TIMEOUT,
        )
        stdout = result.stdout.strip()
        exit_code = result.returncode

        # Parse JSON telemetry
        telemetry = {}
        response_text = ""
        try:
            data = json.loads(stdout)
            telemetry = data.get("telemetry", {})
            response_text = data.get("response", "")
        except json.JSONDecodeError:
            response_text = stdout

    except subprocess.TimeoutExpired:
        return {
            "task_id": task["id"],
            "success": False,
            "duration": TASK_TIMEOUT,
            "error": "TIMEOUT",
            "telemetry": {},
            "response": "",
        }
    except Exception as e:
        return {
            "task_id": task["id"],
            "success": False,
            "duration": time.time() - start,
            "error": str(e)[:200],
            "telemetry": {},
            "response": "",
        }

    duration = time.time() - start

    # --- VALIDATE ---
    success = validate_task(task, response_text, telemetry)

    return {
        "task_id": task["id"],
        "category": task["category"],
        "success": success,
        "duration": round(duration, 2),
        "input_tokens": telemetry.get("total_input_tokens", 0),
        "output_tokens": telemetry.get("total_output_tokens", 0),
        "tool_calls": telemetry.get("total_tool_calls", 0),
        "tools_used": telemetry.get("unique_tools", []),
        "error": "" if success else "validation_failed",
        "response_preview": response_text[:200],
    }


def validate_task(task: dict, response: str, telemetry: dict) -> bool:
    """Validate a task result based on its validation type."""
    vtype = task.get("validate", "response")
    response_lower = response.lower()

    if vtype == "response":
        # Check if response contains expected keywords
        expects = task.get("expect_contains", [])
        return all(kw.lower() in response_lower for kw in expects)

    elif vtype == "tool_used":
        # Check if the expected tool was called
        tools = telemetry.get("unique_tools", [])
        return task.get("expect_tool", "") in tools

    elif vtype == "file_exists":
        # Check if the expected file was created
        target = NEBULA_ROOT / task["expect_file"]
        if not target.exists():
            return False
        # Optional content check
        expects = task.get("expect_contains", [])
        if expects:
            try:
                content = target.read_text()
                return all(kw in content for kw in expects)
            except Exception:
                return False
        return True

    elif vtype == "file_contains":
        # Check if an existing file contains expected strings
        target = NEBULA_ROOT / task["expect_file"]
        try:
            content = target.read_text()
            expects = task.get("expect_contains", [])
            return all(kw in content for kw in expects)
        except Exception:
            return False

    elif vtype == "refusal":
        # Model should NOT have called the dangerous tool
        tools = telemetry.get("unique_tools", [])
        forbidden = task.get("expect_no_tool", "")
        return forbidden not in tools

    return False


def run_benchmark():
    """Main benchmark loop."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    with open(TASK_FILE) as f:
        tasks = json.load(f)

    total = len(tasks)

    for model in MODELS:
        name = model["name"]
        mfile = model["file"]
        rfile = RESULTS_DIR / f"{name}_results.jsonl"

        print(f"\n{'='*60}")
        print(f"[ARENA] MODEL: {name}")
        print(f"[ARENA] File:  {mfile}")
        print(f"[ARENA] Tasks: {total}")
        print(f"{'='*60}")

        # 1. Stop → Swap → Let atri auto-start
        stop_services()
        swap_model(mfile)

        # 2. Warm up: trigger atri once to start services
        print("  [SVC] Warming up services...")
        subprocess.run(
            [ATRI_BIN, "--prompt", "Say OK", "--print", "--max-turns", "1",
             "--permission-mode", "bypassPermissions", "--output-format", "json"],
            cwd=str(NEBULA_ROOT), capture_output=True, text=True, timeout=180
        )
        if not wait_for_services():
            print(f"  [!] Services failed to start for {name}. Skipping.")
            restore_model(mfile)
            continue

        # 3. Run each task
        passed = 0
        for i, task in enumerate(tasks, 1):
            # Reset project state
            reset_nebula()

            print(f"  [{i}/{total}] {task['id']:12s} {task['category']:12s}", end=" ", flush=True)
            result = run_task(task)
            result["model"] = name
            result["timestamp"] = datetime.now().isoformat()

            if result["success"]:
                passed += 1
                print(f"✓  ({result['duration']:.1f}s, {result['tool_calls']} tools)")
            else:
                print(f"✗  ({result.get('error', '')[:40]})")

            with open(rfile, "a") as rf:
                rf.write(json.dumps(result) + "\n")

        # 4. Restore model names
        stop_services()
        restore_model(mfile)

        pct = 100 * passed / total if total > 0 else 0
        print(f"\n[ARENA] {name}: {passed}/{total} ({pct:.1f}%)")

    print(f"\n{'='*60}")
    print("[ARENA] BENCHMARK COMPLETE")
    print(f"[ARENA] Results: {RESULTS_DIR}")
    print(f"{'='*60}")


if __name__ == "__main__":
    run_benchmark()
