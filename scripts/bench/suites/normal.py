"""NORMAL tier — single-step tool-calling competence (BFCL-style) + no-tool QA.

Reuses the proven 19-task eval_harness battery verbatim (converted to BenchTask)
and adds tool-discrimination probes (pick the RIGHT tool, not just any tool).
"""
from __future__ import annotations

from scripts.bench.harness import BenchTask, _used
from scripts.eval_harness import build_tasks as _eval_tasks


def _convert(d: dict) -> BenchTask:
    return BenchTask(
        name=d["name"],
        tier="normal",
        cat=d["cat"],
        msg=d["msg"],
        permission_mode=d.get("permission_mode", "bypassPermissions"),
        confirm=d.get("confirm"),
        plan_mode=d.get("plan_mode", False),
        check=d["check"],
        negative=(d["cat"] == "safety"),
        timeout=180,
    )


def tasks() -> list[BenchTask]:
    out = [_convert(d) for d in _eval_tasks()]

    # Tool-discrimination probes: the model must choose the SPECIALIZED tool.
    out.append(BenchTask(
        name="discriminate_symbol_search", tier="normal", cat="discriminate",
        msg="Using the symbol-search tool (not a text grep), locate the definition of greet.",
        check=lambda r, s: _used(r, "search_symbols") and "app.py" in r["answer"].lower(),
        timeout=180,
    ))
    out.append(BenchTask(
        name="discriminate_repo_map", tier="normal", cat="discriminate",
        msg="Use the repository-map tool to give a one-paragraph overview of this project.",
        check=lambda r, s: _used(r, "get_repo_map") and len(r["answer"]) > 60,
        timeout=180,
    ))
    return out
