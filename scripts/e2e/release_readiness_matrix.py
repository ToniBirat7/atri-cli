#!/usr/bin/env python3
"""Phase 6 release-readiness matrix runner.

Scenarios:
- fresh-install: verify one-command installer path creates working launcher.
- first-run: boot orchestrator and run live readiness harness once.
- restart: run readiness harness twice to validate restart consistency.
- recovery: cleanup local runtime artifacts and verify readiness recovers.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        command,
        cwd=str(cwd or ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        if proc.stdout:
            print(proc.stdout.rstrip())
        if proc.stderr:
            print(proc.stderr.rstrip(), file=sys.stderr)
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(command)}")
    return proc


def _run_harness(python_exe: Path, report_name: str) -> None:
    report_path = ROOT / "benchmark_reports" / report_name
    report_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            str(python_exe),
            str(ROOT / "scripts" / "benchmarks" / "live_readiness_harness.py"),
            "--workspace",
            str(ROOT),
            "--python",
            str(python_exe),
            "--iterations",
            "1",
            "--timeout",
            "90",
            "--report-file",
            str(report_path),
        ]
    )


def scenario_fresh_install(python_exe: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="atri-phase6-install-") as tmp:
        tmp_root = Path(tmp)
        install_root = tmp_root / "share"
        bin_root = tmp_root / "bin"
        _run(
            [
                str(python_exe),
                str(ROOT / "scripts" / "install_cli.py"),
                "--from-local-repo",
                str(ROOT),
                "--install-root",
                str(install_root),
                "--bin-root",
                str(bin_root),
            ]
        )

        _run([str(bin_root / "atri-cli"), "--help"])
        # Compatibility alias should still be functional for this release cycle.
        _run([str(bin_root / "tarbar"), "--help"])


def scenario_first_run(python_exe: Path) -> None:
    _run_harness(python_exe, "phase6-first-run.json")


def scenario_restart(python_exe: Path) -> None:
    _run_harness(python_exe, "phase6-restart-pass1.json")
    _run_harness(python_exe, "phase6-restart-pass2.json")


def scenario_recovery(python_exe: Path) -> None:
    _run(
        [
            str(python_exe),
            str(ROOT / "scripts" / "reset_local_state.py"),
            "--yes",
        ]
    )
    _run_harness(python_exe, "phase6-recovery.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run release-readiness scenario")
    parser.add_argument(
        "--scenario",
        required=True,
        choices=("fresh-install", "first-run", "restart", "recovery"),
        help="Release-readiness scenario to run",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable to use",
    )
    args = parser.parse_args()

    python_exe = Path(args.python)

    if args.scenario == "fresh-install":
        scenario_fresh_install(python_exe)
    elif args.scenario == "first-run":
        scenario_first_run(python_exe)
    elif args.scenario == "restart":
        scenario_restart(python_exe)
    elif args.scenario == "recovery":
        scenario_recovery(python_exe)

    print(f"phase6 scenario passed: {args.scenario}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
