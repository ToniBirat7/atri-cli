"""MEDIUM tier — multi-step chains, cross-file refactor, web synthesis, judged prose."""
from __future__ import annotations

from scripts.bench.harness import BenchTask, _used
from scripts.bench.rubrics import Rubric
from scripts.bench.scoring import file_contains


def _refactor_done(r, s) -> bool:
    files = ["core.py", "report.py", "cli.py"]
    for f in files:
        if file_contains(s / f, "legacy_total"):
            return False
    # at least the new name must appear in core + one caller
    return file_contains(s / "core.py", "new_total") and (
        file_contains(s / "report.py", "new_total") or file_contains(s / "cli.py", "new_total")
    )


def tasks(with_network: bool = False) -> list[BenchTask]:
    out: list[BenchTask] = []

    # Chained tools: search → read → answer.
    out.append(BenchTask(
        name="chain_grep_read", tier="medium", cat="multistep",
        msg="Find the function `greet` in this project, open the file it lives in, "
            "and tell me exactly what string it returns.",
        check=lambda r, s: _used(r, "grep_codebase", "search_symbols", "bash_exec")
                           and _used(r, "read_text_file", "read_file")
                           and "hi" in r["answer"].lower(),
        timeout=300,
    ))

    # Cross-file refactor on the refactor fixture.
    out.append(BenchTask(
        name="cross_file_rename", tier="medium", cat="refactor",
        fixture="refactor",
        msg="Rename the function `legacy_total` to `new_total` everywhere in this "
            "project — the definition in core.py and all call sites. Keep it working.",
        check=_refactor_done,
        timeout=420, max_turns=16,
    ))

    # Open-ended response quality (no tool; deterministic rubric).
    out.append(BenchTask(
        name="quality_sqlite_vs_pg", tier="medium", cat="quality",
        msg="In 120 words or fewer, explain the main tradeoffs between SQLite and "
            "PostgreSQL for a local-first developer tool. Be concrete.",
        rubric=Rubric(
            any_of=[["sqlite"], ["postgres", "postgresql"]],
            none_of=["i cannot", "as an ai"],
            max_words=170, min_chars=80,
        ),
        check=lambda r, s: not r["tools"],  # should answer from knowledge, no tools
        timeout=300,
    ))

    if with_network:
        # GAIA-style web search + synthesis (network-gated, lenient grounding).
        out.append(BenchTask(
            name="web_python_version", tier="medium", cat="web",
            msg="Search the web for the latest stable Python 3 release and tell me "
                "the version number. Include the source URL you used.",
            check=lambda r, s: _used(r, "search_web", "fetch_url"),
            rubric=Rubric(any_of=[["3.1", "3.2"]], require_url=True),
            timeout=360,
        ))

    return out
