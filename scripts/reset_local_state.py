#!/usr/bin/env python3
"""Reset local caches and database artifacts for a fresh run.

By default this script removes local, reproducible artifacts only.
It does not remove source files and does not touch Docker volumes unless
--with-docker-volumes is explicitly passed.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _remove_path(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return True


def _safe_targets(include_frontend_build: bool) -> list[Path]:
    targets = [
        ROOT / ".pytest_cache",
        ROOT / ".mypy_cache",
        ROOT / ".ruff_cache",
        ROOT / "services" / "orchestrator" / "orchestrator.db",
        ROOT / "benchmark_reports",
    ]
    if include_frontend_build:
        targets.append(ROOT / "apps" / "frontend" / ".next")
    return targets


def _find_recursive_targets() -> list[Path]:
    recursive_targets: list[Path] = []
    scoped_roots = [
        ROOT / "apps",
        ROOT / "services",
        ROOT / "scripts",
        ROOT / "docs",
    ]
    for scoped_root in scoped_roots:
        if not scoped_root.exists():
            continue
        for pattern in ("**/__pycache__", "**/*.pyc", "**/*.pyo"):
            recursive_targets.extend(scoped_root.glob(pattern))
    return recursive_targets


def _clean_docker_volumes() -> tuple[bool, str]:
    cmd = ["docker", "compose", "down", "-v"]
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return False, "docker command not found"

    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "docker compose down -v failed").strip()
        return False, msg
    return True, (proc.stdout or "docker volumes removed").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean caches and local DB artifacts")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    parser.add_argument(
        "--include-frontend-build",
        action="store_true",
        help="Also remove apps/frontend/.next build cache",
    )
    parser.add_argument(
        "--with-docker-volumes",
        action="store_true",
        help="Also run docker compose down -v (destructive to local container data)",
    )
    args = parser.parse_args()

    if not args.yes:
        print("This will remove local caches and sqlite benchmark artifacts.")
        answer = input("Continue? [y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Aborted.")
            return 1

    removed = []
    skipped = []

    for target in _safe_targets(args.include_frontend_build):
        if _remove_path(target):
            removed.append(target)
        else:
            skipped.append(target)

    for target in _find_recursive_targets():
        if _remove_path(target):
            removed.append(target)

    docker_result = None
    if args.with_docker_volumes:
        docker_ok, docker_message = _clean_docker_volumes()
        docker_result = {
            "ok": docker_ok,
            "message": docker_message,
        }

    print("Removed:")
    if removed:
        for item in removed:
            print(f"- {item.relative_to(ROOT)}")
    else:
        print("- (none)")

    print("Skipped (not present):")
    if skipped:
        for item in skipped:
            print(f"- {item.relative_to(ROOT)}")
    else:
        print("- (none)")

    if docker_result is not None:
        print("Docker reset:")
        print(f"- ok: {docker_result['ok']}")
        print(f"- message: {docker_result['message']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
