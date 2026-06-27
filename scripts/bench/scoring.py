"""Programmatic scoring helpers — deterministic, judge-free.

The pytest verdict is the canonical SWE-bench signal: we RE-RUN pytest in the
sandbox ourselves and read the exit code, never trusting the agent's claim.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path


def pytest_passes(sandbox: Path, node: str | None = None, timeout: int = 120) -> bool:
    """Run pytest in the sandbox; True iff exit code 0. `node` scopes to one test."""
    args = [sys.executable, "-m", "pytest", "-q"]
    if node:
        args.append(node)
    try:
        proc = subprocess.run(
            args, cwd=str(sandbox), capture_output=True, text=True, timeout=timeout
        )
        return proc.returncode == 0
    except Exception:
        return False


def file_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def file_contains(path: Path, needle: str) -> bool:
    try:
        return needle in path.read_text(errors="replace")
    except OSError:
        return False


def files_unchanged(paths_and_hashes: dict[Path, str]) -> bool:
    """True iff every file still matches its recorded hash (anti-cheat guard)."""
    return all(file_hash(p) == h for p, h in paths_and_hashes.items())


def is_valid_png(path: Path) -> bool:
    try:
        return path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    except OSError:
        return False


# ── pass@k aggregation ──────────────────────────────────────────────────────

def aggregate(passes: int, runs: int) -> dict:
    """pass@1 = first attempt; pass@k = any attempt over `runs` repeats.

    We treat the run as pass@1 if the first attempt passed, and pass@k if at
    least one of the `runs` attempts passed. (The caller records first-attempt
    separately; here we surface both rates for the report.)"""
    return {
        "passes": passes,
        "runs": runs,
        "rate": (passes / runs) if runs else 0.0,
        "any": passes > 0,
        "all": passes == runs and runs > 0,
    }
