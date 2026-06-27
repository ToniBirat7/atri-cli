"""HARD tier — SWE-bench-style fix-the-tests, refactor-with-tests, big-repo nav."""
from __future__ import annotations

from scripts.bench.harness import BenchTask, _used
from scripts.bench.scoring import pytest_passes


def _fix_tests_check(r, s) -> bool:
    # Canonical SWE-bench signal: harness re-runs pytest, reads exit code.
    return pytest_passes(s)


def tasks() -> list[BenchTask]:
    out: list[BenchTask] = []

    out.append(BenchTask(
        name="swebench_fix_failing_tests", tier="hard", cat="bugfix",
        fixture="broken",
        msg="This project has a failing test suite. Run `pytest -q` to see the "
            "failures, then read the source files and fix the bugs so all tests "
            "pass. Do not edit the tests. Re-run pytest to confirm when done.",
        check=_fix_tests_check,
        timeout=900, max_turns=16,
        meta={"anti_cheat": "test_calc.py"},
    ))

    out.append(BenchTask(
        name="bignav_find_payment", tier="hard", cat="navigation",
        fixture="big",
        msg="Somewhere in this large repository there is a function called "
            "`process_payment`. Find which file defines it and summarize what it "
            "does. Navigate efficiently — do not read every file.",
        check=lambda r, s: ("payments.py" in r["answer"] or "billing/payments" in r["answer"])
                           and _used(r, "grep_codebase", "search_symbols", "get_repo_map", "bash_exec"),
        timeout=600, max_turns=12,
    ))

    return out
