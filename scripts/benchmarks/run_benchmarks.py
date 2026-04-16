#!/usr/bin/env python3
"""Run all benchmark scripts and store reports.

This runner executes the orchestrator and full-pipeline benchmarks and writes
JSON report files under benchmark_reports/.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BENCH_DIR = ROOT / "scripts" / "benchmarks"
REPORT_DIR = ROOT / "benchmark_reports"


def _run(script_name: str) -> tuple[int, dict[str, Any]]:
    cmd = [sys.executable, str(BENCH_DIR / script_name)]
    proc = subprocess.run(cmd, capture_output=True, text=True)

    output = (proc.stdout or "").strip()
    parsed: dict[str, Any]
    if output:
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            parsed = {
                "benchmark": script_name,
                "passed": False,
                "error": "benchmark_output_not_json",
                "stdout": output,
                "stderr": proc.stderr,
            }
    else:
        parsed = {
            "benchmark": script_name,
            "passed": False,
            "error": "empty_output",
            "stderr": proc.stderr,
        }

    parsed["exit_code"] = proc.returncode
    if proc.stderr:
        parsed.setdefault("stderr", proc.stderr)
    return proc.returncode, parsed


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    scripts = [
        "benchmark_orchestrator_e2e.py",
        "benchmark_full_pipeline.py",
    ]

    reports = []
    all_passed = True
    for script in scripts:
        exit_code, data = _run(script)
        all_passed = all_passed and (exit_code == 0) and bool(data.get("passed"))
        report_path = REPORT_DIR / f"{script.replace('.py', '')}_{timestamp}.json"
        report_path.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        reports.append(
            {
                "script": script,
                "exit_code": exit_code,
                "passed": bool(data.get("passed")) and exit_code == 0,
                "report": str(report_path.relative_to(ROOT)),
            }
        )

    summary = {
        "timestamp": timestamp,
        "all_passed": all_passed,
        "reports": reports,
    }
    summary_path = REPORT_DIR / f"summary_{timestamp}.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
