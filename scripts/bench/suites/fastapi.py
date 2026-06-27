"""FASTAPI headline suite — clone the real repo (once), then:
  1. observational unbounded "find and fix all issues" (record behavior, no PASS)
  2. bounded scored: repo-map architecture summary
  3. bounded scored: find + fix ONE injected bug via a targeted pytest node

The runner clones into a tmpfs dir, injects the bug, and points each task's
sandbox at the repo parent. Network/disk gated by the runner.
"""
from __future__ import annotations

from scripts.bench.harness import BenchTask, _used
from scripts.bench.scoring import pytest_passes


def tasks() -> list[BenchTask]:
    out: list[BenchTask] = []

    # 1. The literal user ask — observational, unbounded, no PASS expected.
    out.append(BenchTask(
        name="fastapi_find_and_fix_all", tier="fastapi", cat="megatask",
        fixture="fastapi", observe_only=True,
        msg="This is the FastAPI project. Find the issues in this codebase and fix "
            "them. Start by understanding the structure, then investigate and make "
            "fixes where you find problems.",
        timeout=1200, max_turns=16,
    ))

    # 2. Architecture summary via repo map (bounded, scored).
    out.append(BenchTask(
        name="fastapi_repo_map_summary", tier="fastapi", cat="navigation",
        fixture="fastapi", permission_mode="default",
        msg="Use the repository-map tool to survey this FastAPI project, then give "
            "a high-level summary of its architecture: the main package, key "
            "modules, and what they are responsible for. Do not edit anything.",
        check=lambda r, s: _used(r, "get_repo_map", "list_directory", "directory_tree")
                           and len(r["answer"]) > 200
                           and any(k in r["answer"].lower()
                                   for k in ("rout", "applic", "starlette", "depend", "request")),
        timeout=600, max_turns=6,
    ))

    # 3. Find + fix ONE injected bug, verified by a targeted pytest node.
    out.append(BenchTask(
        name="fastapi_fix_injected_bug", tier="fastapi", cat="bugfix",
        fixture="fastapi",
        msg="A bug was introduced in the file `_bench_util.py` at the repository "
            "root. The test `test_bench_util.py` fails because of it. Run that one "
            "test to see the failure, fix the bug in `_bench_util.py` only, then "
            "re-run that one test to confirm it passes.",
        check=lambda r, s: pytest_passes(s / "fastapi", node="test_bench_util.py::test_clamp_lower_bound"),
        timeout=900, max_turns=14,
        meta={"node": "test_bench_util.py::test_clamp_lower_bound"},
    ))

    return out
