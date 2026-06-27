#!/usr/bin/env python3
"""Bench runner — preflight, warmup, sequential execution, incremental report.

Run from repo root:
  services/orchestrator/.venv/bin/python -m scripts.bench.runner --tier all
  python -m scripts.bench.runner --tier normal --orch http://127.0.0.1:8001
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
import urllib.request
from pathlib import Path

from scripts.bench import fixtures as fx
from scripts.bench.harness import (
    BenchTask, fetch_active_profile, metrics_snapshot, run_agent_ex, tool_error_count,
)
from scripts.bench.report import Report
from scripts.bench.scoring import file_hash
from scripts.bench.suites import (
    adversarial, fastapi, hard, medium, multimodal, normal,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH_DEFAULT = "http://127.0.0.1:8001"

FIXTURE_BUILDERS = {
    "default": fx.make_sandbox,
    "broken": fx.make_broken_repo,
    "refactor": fx.make_refactor_repo,
    "big": fx.make_big_repo,
    "media": fx.make_media_assets,
    "injection": fx.make_injection_sandbox,
}

TIER_ORDER = ["normal", "medium", "hard", "fastapi", "multimodal", "adversarial"]
_NO_TOOL_CATS = {"no-tool", "quality"}


def _ready(orch: str, timeout: int = 5) -> bool:
    try:
        with urllib.request.urlopen(f"{orch}/ready", timeout=timeout) as r:
            r.read()
        return True
    except Exception:
        return False


def _llama_ready(timeout: int = 5) -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _wait_ready(orch: str, max_wait: int = 600) -> bool:
    """Poll until both orchestrator /ready and llama /health are up (MoE load is slow)."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if _ready(orch) and _llama_ready():
            return True
        time.sleep(5)
    return _ready(orch)


def _measure_tok_per_s(n: int = 6) -> float:
    """Average generation tok/s from the most recent `eval time` lines in llama.log."""
    log = REPO_ROOT / "llama.log"
    try:
        text = log.read_text(errors="replace")
    except OSError:
        return 0.0
    vals = re.findall(r"eval time =.*?,\s*([\d.]+)\s*tokens per second", text)
    # Drop prompt-eval lines (much higher); 'eval time' (not 'prompt eval time')
    gen = re.findall(r"\n\s+eval time =.*?,\s*([\d.]+)\s*tokens per second", text)
    use = gen[-n:] if gen else vals[-n:]
    nums = [float(v) for v in use]
    return round(sum(nums) / len(nums), 1) if nums else 0.0


def build_battery(tiers: list[str], with_network: bool) -> list[BenchTask]:
    out: list[BenchTask] = []
    if "normal" in tiers:
        out += normal.tasks()
    if "medium" in tiers:
        out += medium.tasks(with_network=with_network)
    if "hard" in tiers:
        out += hard.tasks()
    if "fastapi" in tiers and with_network:
        # scored tasks first, observational last (it mutates the shared clone)
        ft = fastapi.tasks()
        ft.sort(key=lambda t: t.observe_only)
        out += ft
    if "multimodal" in tiers:
        out += multimodal.tasks()
    if "adversarial" in tiers:
        out += adversarial.tasks()
    return out


def _score(task: BenchTask, r: dict, sandbox: Path) -> tuple[bool, str]:
    notes = []
    prog_ok = True
    if task.check is not None:
        try:
            prog_ok = bool(task.check(r, sandbox))
        except Exception as e:
            prog_ok = False
            notes.append(f"check-error:{str(e)[:40]}")
    rub_ok = True
    if task.rubric is not None:
        rub_ok, why = task.rubric.score(r["answer"])
        if not rub_ok:
            notes.append(f"rubric:{why}")
    return (prog_ok and rub_ok), "; ".join(notes)


def run_task(orch: str, task: BenchTask, fastapi_parent: Path | None) -> dict:
    # Build / locate the sandbox.
    if task.fixture == "fastapi":
        sandbox = fastapi_parent
        allowed = fastapi_parent / "fastapi"
    else:
        sandbox = FIXTURE_BUILDERS[task.fixture]()
        allowed = sandbox

    if task.setup:
        try:
            task.setup(sandbox)
        except Exception:
            pass

    # Anti-cheat: snapshot a file that must NOT be edited (e.g. the test file).
    guard_path = None
    guard_hash = None
    if task.meta.get("anti_cheat"):
        guard_path = sandbox / task.meta["anti_cheat"]
        guard_hash = file_hash(guard_path)

    note = ""
    try:
        r = run_agent_ex(
            orch, task.msg, allowed,
            permission_mode=task.permission_mode,
            confirm=task.confirm,
            timeout=task.timeout,
            plan_mode=task.plan_mode,
            max_turns=task.max_turns,
        )
    except Exception as e:
        r = {"tools": [], "tool_results": [], "confirmations": [], "answer": "",
             "turns": 0, "total_tool_calls": 0, "status": "error", "outcome": "error",
             "tokens": {"total": 0, "completion": 0}, "cid": None, "elapsed": 0.0,
             "error": str(e)[:120]}
        note = f"exception:{str(e)[:60]}"

    if task.observe_only:
        passed = None
    else:
        passed, snote = _score(task, r, sandbox)
        if snote:
            note = (note + "; " + snote).strip("; ")
        # Anti-cheat: if the protected file changed, it's a cheat → FAIL.
        if guard_path is not None and file_hash(guard_path) != guard_hash:
            passed = False
            note = (note + "; edited-protected-file").strip("; ")

    tool_acc = None
    if (not task.observe_only and not task.negative
            and task.cat not in _NO_TOOL_CATS):
        tool_acc = bool(passed)

    record = {
        "name": task.name, "tier": task.tier, "cat": task.cat,
        "observe_only": task.observe_only, "negative": task.negative,
        "passed": passed,
        "turns": r.get("turns", 0),
        "tool_calls": r.get("total_tool_calls", len(r.get("tools", []))),
        "tools": r.get("tools", []),
        "tool_errors": tool_error_count(r),
        "tool_accuracy": tool_acc,
        "tokens": r.get("tokens", {}).get("total", 0),
        "completion_tokens": r.get("tokens", {}).get("completion", 0),
        "status": r.get("status", ""),
        "outcome": r.get("outcome", ""),
        "elapsed": r.get("elapsed", 0.0),
        "answer": r.get("answer", "")[:600],
        "note": note,
    }

    # Cleanup non-shared sandboxes.
    if task.fixture != "fastapi":
        shutil.rmtree(sandbox, ignore_errors=True)
    return record


def warmup(orch: str) -> None:
    print("[bench] warmup (priming model + cache)...")
    sb = fx.make_sandbox()
    try:
        for msg in ("Reply with only the word ready.",
                    "List the files in the current directory."):
            try:
                run_agent_ex(orch, msg, sb, timeout=300)
            except Exception as e:
                print(f"[bench] warmup request failed (continuing): {str(e)[:80]}")
    finally:
        shutil.rmtree(sb, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--orch", default=ORCH_DEFAULT)
    ap.add_argument("--tier", default="all",
                    help="comma list of tiers, or 'all' (excludes fastapi unless --with-network)")
    ap.add_argument("--with-network", action="store_true",
                    help="enable web-search + FastAPI clone tasks (needs internet)")
    ap.add_argument("--repeat", type=int, default=1, help="pass@k repeats per task")
    ap.add_argument("--out", default=str(REPO_ROOT / "scripts" / "bench" / "reports"))
    ap.add_argument("--stamp", default=str(int(time.time())) if False else "run",
                    help="report filename stamp (Date.now unavailable in workflows)")
    ap.add_argument("--no-warmup", action="store_true")
    args = ap.parse_args()

    # ── Preflight ────────────────────────────────────────────────────────────
    if not _wait_ready(args.orch, max_wait=900):
        print(f"[bench] ERROR: services not ready at {args.orch} / llama:8000")
        return 2

    profile = fetch_active_profile(args.orch) or "(unknown)"
    tok_s = _measure_tok_per_s()
    m_start = metrics_snapshot(args.orch)

    tiers = TIER_ORDER if args.tier == "all" else [t.strip() for t in args.tier.split(",")]
    tiers = [t for t in TIER_ORDER if t in tiers]  # canonical order
    battery = build_battery(tiers, args.with_network)

    # Resolve the model path from the live config for the report header.
    model_path = ""
    try:
        import json
        cfg = json.loads((REPO_ROOT / "runtime" / "llm" / "launch_config.json").read_text())
        model_path = cfg.get("model_path", "")
    except Exception:
        pass

    header = {
        "stamp": args.stamp,
        "tiers": tiers,
        "with_network": args.with_network,
        "repeat": args.repeat,
        "tok_per_s": tok_s,
        "gpu": (m_start.get("gpu_name") if isinstance(m_start, dict) else "") or "RTX 3060",
        "ram_mb": "31267",
        "metrics_start": m_start,
    }
    report = Report(Path(args.out), model_path or "26B", profile, header)

    print(f"[bench] model={Path(model_path).name or '?'} profile={profile} "
          f"tok/s≈{tok_s} tiers={tiers} tasks={len(battery)} repeat={args.repeat}")

    if not args.no_warmup:
        warmup(args.orch)

    # ── FastAPI clone (once) ──────────────────────────────────────────────────
    fastapi_parent = None
    if "fastapi" in tiers and args.with_network:
        try:
            print("[bench] cloning fastapi (shallow, pinned tag)...")
            fastapi_parent = fx.clone_fastapi()
            fx.inject_fastapi_bug(fastapi_parent)
            print(f"[bench] fastapi ready at {fastapi_parent}")
        except Exception as e:
            print(f"[bench] fastapi clone failed, skipping suite: {str(e)[:120]}")
            battery = [t for t in battery if t.fixture != "fastapi"]

    # ── Execute sequentially ──────────────────────────────────────────────────
    t0 = time.time()
    for i, task in enumerate(battery, 1):
        passes = 0
        first_pass = None
        last = None
        # Observational tasks run once regardless of --repeat.
        n = 1 if task.observe_only else args.repeat
        for k in range(n):
            rec = run_task(args.orch, task, fastapi_parent)
            last = rec
            if not task.observe_only:
                ok = bool(rec["passed"])
                passes += int(ok)
                if first_pass is None:
                    first_pass = ok
        # Fold pass@k into the recorded verdict.
        if not task.observe_only:
            last["passed"] = passes > 0
            last["pass1"] = bool(first_pass)
            last["passk"] = f"{passes}/{n}"
        report.add(last)

        verdict = ("OBSERVE" if task.observe_only
                   else ("PASS" if last["passed"] else "FAIL"))
        print(f"[bench] {i:2}/{len(battery)} [{verdict:7}] {task.tier:11} {task.name:32} "
              f"turns={last.get('turns')} tools={last.get('tool_calls')} "
              f"{last.get('elapsed')}s {('· '+last['note']) if last.get('note') else ''}")

    wall = round(time.time() - t0, 1)
    report.header["wall_clock_s"] = wall
    report.header["metrics_end"] = metrics_snapshot(args.orch)
    report.header["tok_per_s"] = _measure_tok_per_s()  # refresh after the run
    report._flush_json()
    md = report.write_markdown()

    if fastapi_parent is not None:
        shutil.rmtree(fastapi_parent, ignore_errors=True)

    s = report.records
    scored = [r for r in s if not r.get("observe_only")]
    passed = sum(int(bool(r.get("passed"))) for r in scored)
    print("=" * 70)
    print(f"[bench] DONE  scored {passed}/{len(scored)}  wall={wall}s  "
          f"tok/s≈{report.header['tok_per_s']}")
    print(f"[bench] JSON: {report.json_path}")
    print(f"[bench] MD:   {md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
