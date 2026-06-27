"""Incremental JSON + final markdown report writer.

Writes the JSON after EVERY task (flush) so a mid-run kill still yields partial
data — essential for multi-hour 26B runs.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.bench.metrics import summarize


class Report:
    def __init__(self, out_dir: Path, model: str, profile: str, header: dict):
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.model = model
        self.profile = profile
        self.header = header
        self.records: list[dict] = []
        stamp = header.get("stamp", "run")
        base = f"bench_{Path(model).stem or 'model'}_{stamp}"
        self.json_path = out_dir / f"{base}.json"
        self.md_path = out_dir / f"{base}.md"

    def add(self, record: dict) -> None:
        self.records.append(record)
        self._flush_json()

    def _flush_json(self) -> None:
        payload = {
            "model": self.model,
            "profile": self.profile,
            "header": self.header,
            "summary": summarize(self.records),
            "records": self.records,
        }
        tmp = self.json_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self.json_path)

    def write_markdown(self) -> Path:
        s = summarize(self.records)
        h = self.header
        lines: list[str] = []
        lines.append("# Atri Code — 26B Stress-Test Dashboard\n")
        lines.append(f"- **Model:** `{Path(self.model).name}`")
        lines.append(f"- **Profile:** `{self.profile}`")
        lines.append(f"- **Hardware:** {h.get('gpu','?')} / {h.get('ram_mb','?')} MB RAM")
        lines.append(f"- **Measured throughput:** {h.get('tok_per_s','?')} tok/s (target ≥26)")
        lines.append(f"- **Repeats (pass@k):** k={h.get('repeat',1)}")
        lines.append(f"- **Total wall-clock:** {h.get('wall_clock_s','?')} s")
        lines.append("")
        ov = s["overall"]
        lines.append(f"## Overall: {ov['passed']}/{ov['scored']} "
                     f"({round(ov['rate']*100)}%) scored · {ov['observed']} observational\n")

        lines.append("### By tier")
        lines.append("| Tier | Pass | N | Rate |")
        lines.append("|------|------|---|------|")
        for tier, d in s["by_tier"].items():
            lines.append(f"| {tier} | {d['passed']} | {d['n']} | {round(d['rate']*100)}% |")
        lines.append("")

        lines.append("### By category")
        lines.append("| Category | Pass | N | Rate |")
        lines.append("|----------|------|---|------|")
        for cat, d in s["by_cat"].items():
            lines.append(f"| {cat} | {d['passed']} | {d['n']} | {round(d['rate']*100)}% |")
        lines.append("")

        lat, tools, rec, hal, tok = (s["latency"], s["tools"], s["recovery"],
                                     s["hallucination"], s["tokens"])
        lines.append("### Health metrics")
        lines.append(f"- **Latency:** p50 {lat['p50']}s · p95 {lat['p95']}s · max {lat['max']}s")
        lines.append(f"- **Tool calls:** {tools['total_calls']} total · "
                     f"{tools['total_errors']} errors ({round(tools['error_rate']*100)}%) · "
                     f"accuracy {('—' if tools['accuracy'] is None else str(round(tools['accuracy']*100))+'%')}")
        lines.append(f"- **Recovery:** "
                     f"{('—' if rec['rate'] is None else str(round(rec['rate']*100))+'%')} "
                     f"({rec['recovered']}/{rec['had_error']} errored tasks recovered)")
        lines.append(f"- **Hallucination (negatives):** "
                     f"{('—' if hal['rate'] is None else str(round(hal['rate']*100))+'%')} "
                     f"({hal['failed']}/{hal['negatives']} failed graceful-degradation)")
        lines.append(f"- **Tokens:** {tok['total']} total ({tok['completion']} completion)")
        lines.append("")

        # Per-task detail (esp. failures + observational trajectories).
        lines.append("### Task detail")
        lines.append("| Task | Tier | Verdict | Turns | Tools | Tok | Elapsed | Note |")
        lines.append("|------|------|---------|-------|-------|-----|---------|------|")
        for r in self.records:
            verdict = ("OBSERVE" if r.get("observe_only")
                       else ("PASS" if r.get("passed") else "FAIL"))
            note = (r.get("note") or "")[:60]
            lines.append(
                f"| {r['name']} | {r['tier']} | {verdict} | {r.get('turns','')} | "
                f"{r.get('tool_calls','')} | {r.get('tokens','')} | "
                f"{r.get('elapsed','')}s | {note} |"
            )
        lines.append("")

        self.md_path.write_text("\n".join(lines))
        return self.md_path
