"""Aggregate per-task records into the senior-eng dashboard metrics."""
from __future__ import annotations


def percentile(values: list[float], p: float) -> float:
    """Linear-interpolated percentile (p in [0,100]). Returns 0.0 if empty."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    k = (len(s) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return round(s[lo] + (s[hi] - s[lo]) * frac, 1)


def summarize(records: list[dict]) -> dict:
    """records: list of per-run dicts with keys produced by the runner:
    tier, cat, passed(bool), observe_only(bool), negative(bool), elapsed,
    turns, tool_calls, tool_errors, tokens(int), tool_accuracy(bool|None)."""
    scored = [r for r in records if not r.get("observe_only")]
    latencies = [r["elapsed"] for r in records if r.get("elapsed")]

    by_tier: dict[str, list[int]] = {}
    by_cat: dict[str, list[int]] = {}
    for r in scored:
        by_tier.setdefault(r["tier"], [0, 0])
        by_tier[r["tier"]][0] += int(bool(r.get("passed")))
        by_tier[r["tier"]][1] += 1
        by_cat.setdefault(r["cat"], [0, 0])
        by_cat[r["cat"]][0] += int(bool(r.get("passed")))
        by_cat[r["cat"]][1] += 1

    total_tool_calls = sum(r.get("tool_calls", 0) for r in records)
    total_tool_errors = sum(r.get("tool_errors", 0) for r in records)

    # Recovery: tasks that had >=1 tool error but still passed.
    had_err = [r for r in scored if r.get("tool_errors", 0) > 0]
    recovered = [r for r in had_err if r.get("passed")]

    # Hallucination rate: failures among negative (graceful-degradation) tasks.
    negatives = [r for r in scored if r.get("negative")]
    halluc = [r for r in negatives if not r.get("passed")]

    acc = [r for r in scored if r.get("tool_accuracy") is not None]
    acc_ok = [r for r in acc if r.get("tool_accuracy")]

    passed_total = sum(int(bool(r.get("passed"))) for r in scored)

    return {
        "overall": {
            "passed": passed_total,
            "scored": len(scored),
            "rate": round(passed_total / len(scored), 3) if scored else 0.0,
            "observed": len(records) - len(scored),
        },
        "by_tier": {k: {"passed": v[0], "n": v[1],
                        "rate": round(v[0] / v[1], 3) if v[1] else 0.0}
                    for k, v in sorted(by_tier.items())},
        "by_cat": {k: {"passed": v[0], "n": v[1],
                       "rate": round(v[0] / v[1], 3) if v[1] else 0.0}
                   for k, v in sorted(by_cat.items())},
        "latency": {
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
            "max": round(max(latencies), 1) if latencies else 0.0,
        },
        "tools": {
            "total_calls": total_tool_calls,
            "total_errors": total_tool_errors,
            "error_rate": round(total_tool_errors / total_tool_calls, 3) if total_tool_calls else 0.0,
            "accuracy": round(len(acc_ok) / len(acc), 3) if acc else None,
        },
        "recovery": {
            "had_error": len(had_err),
            "recovered": len(recovered),
            "rate": round(len(recovered) / len(had_err), 3) if had_err else None,
        },
        "hallucination": {
            "negatives": len(negatives),
            "failed": len(halluc),
            "rate": round(len(halluc) / len(negatives), 3) if negatives else None,
        },
        "tokens": {
            "total": sum(r.get("tokens", 0) for r in records),
            "completion": sum(r.get("completion_tokens", 0) for r in records),
        },
    }
