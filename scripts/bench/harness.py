"""Bench harness primitives — extends the proven eval_harness machinery.

`run_agent_ex` is a superset of eval_harness.run_agent: it ALSO captures the
token-usage SSE events (agent_loop.py emits {type:"usage", prompt_tokens, ...}),
agent_complete.total_tool_calls / status / outcome, and per-tool status — all of
which the lean run_agent drops. It also folds in plan_mode (a body flag) so the
runner has one code path. make_sandbox / run_multiturn / _used are reused as-is.
"""
from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# Reuse the battle-tested sandbox + helpers from the existing harness.
from scripts.eval_harness import _used, make_sandbox  # noqa: F401  (re-export)

ORCH_DEFAULT = "http://127.0.0.1:8001"


@dataclass
class BenchTask:
    """One benchmark task. `check` (programmatic) and/or `rubric` (deterministic
    text scoring) decide PASS. `negative=True` marks hallucination/safety probes
    where the right answer is a graceful refusal."""
    name: str
    tier: str
    cat: str
    msg: str
    fixture: str = "default"          # which fixtures.py builder to use
    permission_mode: str = "bypassPermissions"
    confirm: Optional[bool] = None
    plan_mode: bool = False
    max_turns: Optional[int] = None
    timeout: int = 240               # wall-clock budget (s); tier-scaled by runner
    check: Optional[Callable] = None  # check(result, sandbox) -> bool
    rubric: object = None            # rubrics.Rubric (deterministic) or None
    negative: bool = False
    observe_only: bool = False       # record trajectory, no PASS/FAIL (e.g. fastapi)
    setup: Optional[Callable] = None  # setup(sandbox) -> None | str (extra prep)
    meta: dict = field(default_factory=dict)


def _coerce_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def run_agent_ex(
    orch: str,
    message: str,
    allowed_dir: Path,
    permission_mode: str = "bypassPermissions",
    conversation_id: Optional[str] = None,
    confirm: Optional[bool] = None,
    timeout: int = 240,
    plan_mode: bool = False,
    max_turns: Optional[int] = None,
) -> dict:
    """Send one chat request, parse the full SSE trajectory, and capture telemetry.

    Returns a dict with: tools, tool_results[{tool,status,result}], confirmations,
    answer, turns, total_tool_calls, status, outcome, tokens{prompt,completion,
    total}, cid, elapsed, error(optional).
    """
    body: dict = {
        "message": message,
        "permission_mode": permission_mode,
        "allowed_directory": str(allowed_dir),
    }
    if conversation_id:
        body["conversation_id"] = conversation_id
    if plan_mode:
        body["plan_mode"] = True
    if max_turns is not None:
        body["max_turns"] = max_turns  # honored if the orchestrator supports it

    req = urllib.request.Request(
        f"{orch}/chat/stream",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    tools: list[str] = []
    tool_results: list[dict] = []
    confirmations: list[str] = []
    answer = ""
    cid = conversation_id
    turns = 0
    total_tool_calls = 0
    status = ""
    outcome = ""
    tok = {"prompt": 0, "completion": 0, "total": 0}
    t0 = time.time()

    def _absorb_usage(d: dict) -> None:
        # Usage events accumulate per turn; sum them. Accept either bare or nested.
        if "prompt_tokens" in d or "completion_tokens" in d or "total_tokens" in d:
            tok["prompt"] += _coerce_int(d.get("prompt_tokens"))
            tok["completion"] += _coerce_int(d.get("completion_tokens"))
            tok["total"] += _coerce_int(d.get("total_tokens"))

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload == "[DONE]":
                break
            try:
                p = json.loads(payload)
            except json.JSONDecodeError:
                continue

            ptype = p.get("type")
            if ptype == "session_started":
                cid = p.get("conversation_id") or cid
            elif ptype == "assistant_delta":
                answer += p.get("content", "")
            elif ptype == "usage":
                _absorb_usage(p)

            ev = p.get("event", {}) or {}
            et = ev.get("type")
            if et == "tool_call_start":
                tools.append(ev.get("tool_name"))
            elif et == "tool_call_result":
                tool_results.append({
                    "tool": ev.get("tool_name"),
                    "status": ev.get("status"),
                    "result": str(ev.get("tool_result") or ev.get("error") or ""),
                })
            elif et == "usage":
                _absorb_usage(ev)
            elif et == "agent_complete":
                turns = _coerce_int(ev.get("turns"))
                total_tool_calls = _coerce_int(ev.get("total_tool_calls"))
                status = str(ev.get("status") or "")
                outcome = str(ev.get("outcome") or ev.get("status") or "")
            elif et == "tool_confirmation_requested":
                confirmations.append(ev.get("tool_name"))
                if confirm is not None and cid:
                    cbody = json.dumps({
                        "request_id": ev.get("request_id"),
                        "approved": confirm,
                    }).encode()
                    try:
                        urllib.request.urlopen(
                            urllib.request.Request(
                                f"{orch}/confirm/{cid}", data=cbody,
                                headers={"Content-Type": "application/json"},
                                method="POST",
                            ), timeout=15,
                        ).read()
                    except Exception:
                        pass

    return {
        "tools": tools,
        "tool_results": tool_results,
        "confirmations": confirmations,
        "answer": answer.strip(),
        "turns": turns,
        "total_tool_calls": total_tool_calls or len(tools),
        "status": status,
        "outcome": outcome,
        "tokens": tok,
        "cid": cid,
        "elapsed": round(time.time() - t0, 1),
    }


def tool_error_count(result: dict) -> int:
    """Number of tool calls that errored or were denied."""
    return sum(
        1 for tr in result.get("tool_results", [])
        if (tr.get("status") or "").lower() in ("error", "denied", "failed")
    )


def metrics_snapshot(orch: str) -> dict:
    """Snapshot the orchestrator's process-wide /metrics counters (cross-check)."""
    try:
        with urllib.request.urlopen(f"{orch}/metrics", timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return {}


def fetch_active_profile(orch: str) -> str:
    """Best-effort read of the active default prompt profile from /models or /health."""
    for path in ("/models", "/health", "/ready"):
        try:
            with urllib.request.urlopen(f"{orch}{path}", timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            for key in ("default_profile", "prompt_profile", "profile"):
                if isinstance(data, dict) and data.get(key):
                    return str(data[key])
        except Exception:
            continue
    return ""
