"""
Atri CLI Live Agentic Harness — 25 prompts covering full tool surface.

Run against a live stack:
    cd services/orchestrator
    ORCHESTRATOR_URL=http://localhost:8001 \
    ORCHESTRATOR_API_KEY=secret \
    .venv/bin/python tests/test_harness.py

Outputs a JSON report + human-readable summary to stdout.
"""

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field

import httpx

BASE_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8001")
API_KEY  = os.getenv("ORCHESTRATOR_API_KEY", "secret")
TIMEOUT  = 90  # seconds per prompt

HEADERS = {
    "Content-Type": "application/json",
    "X-API-Key": API_KEY,
}

# ── Prompt catalogue ──────────────────────────────────────────────────────────
#
# Each entry:  (id, category, prompt, expected_tool, description)
#   expected_tool: None = no tool call expected
#                  str  = at least one call to this tool expected
#
PROMPTS: list[tuple[str, str, str, str | None, str]] = [
    # ── Pure knowledge / no-tool ──────────────────────────────────────────────
    ("K01", "knowledge", "What is 7 multiplied by 8?", None,
     "Simple arithmetic — no tool needed"),
    ("K02", "knowledge", "Explain what the ReAct prompting pattern is in 2 sentences.", None,
     "LLM knowledge — concise factual answer"),
    ("K03", "knowledge", "What does the MCP acronym stand for in the context of AI agents?", None,
     "Domain knowledge — no tool"),
    ("K04", "knowledge", "List 3 differences between SQLite and PostgreSQL.", None,
     "Comparison — no tool"),

    # ── Filesystem: list / read ───────────────────────────────────────────────
    ("F01", "filesystem", "List the files in the current working directory.", "list_directory",
     "Basic directory listing"),
    ("F02", "filesystem", "List the files inside services/orchestrator/.", "list_directory",
     "Sub-directory listing"),
    ("F03", "filesystem",
     "Read the file services/orchestrator/config.py and tell me what the default value of max_turns is.",
     "read_text_file", "File read + extract value"),
    ("F04", "filesystem",
     "Read services/orchestrator/agent_loop.py and summarise what _thinking_for_turn() does.",
     "read_text_file", "File read + code comprehension"),
    ("F05", "filesystem",
     "How many Python files are in services/orchestrator/? Just give me the count.",
     "list_directory", "Count files via tool"),

    # ── Grep / search ─────────────────────────────────────────────────────────
    ("G01", "grep", "Search the codebase for all uses of 'thinking_mode' and list the files.", "grep_codebase",
     "Codebase-wide symbol search"),
    ("G02", "grep", "Find every file that imports 'AgentLoop'.", "grep_codebase",
     "Import search"),
    ("G03", "grep", "How many times does the string 'tool_call' appear across the services/ directory?", "grep_codebase",
     "Frequency count via grep"),

    # ── Bash execution ────────────────────────────────────────────────────────
    ("B01", "bash", "Run `echo 'atri test harness active'` and show me the output.", "bash_exec",
     "Trivial bash exec"),
    ("B02", "bash", "Run `python3 --version` and tell me the Python version.", "bash_exec",
     "Version probe via bash"),
    ("B03", "bash", "Run `ls -lh models/` and show me the model files and their sizes.", "bash_exec",
     "List models directory with sizes"),
    ("B04", "bash", "Use bash to count the number of lines in services/orchestrator/api.py.", "bash_exec",
     "Line count via wc -l"),

    # ── Todo management ───────────────────────────────────────────────────────
    ("TD01", "todo",
     "Create a todo list with these 3 items: 1) Test E4B model 2) Fix flash attention flag 3) Add hallucination guard.",
     "todo_write", "Todo creation"),
    ("TD02", "todo", "Read the current todo list.", "todo_read",
     "Todo read — depends on TD01 having run"),

    # ── Multi-step / chained tools ────────────────────────────────────────────
    ("M01", "multi-step",
     "Find all files named '*.py' in services/mcp/ and then read main.py to tell me which tools it exposes.",
     "list_directory", "Chain: list then read"),
    ("M02", "multi-step",
     "Search for 'bash_exec' in the codebase, then read the file where it is defined and explain what the _BLOCKED_COMMAND_PATTERNS list does.",
     "grep_codebase", "Chain: grep then read"),
    ("M03", "multi-step",
     "List the files in scripts/, then run the detect_hardware.py script and show me the output.",
     "list_directory", "Chain: list then bash_exec"),

    # ── Error handling / edge cases ───────────────────────────────────────────
    ("E01", "edge",
     "Read the file services/orchestrator/nonexistent_file.py and tell me what is in it.",
     "read_text_file", "File not found — graceful error"),
    ("E02", "edge",
     "Run `rm -rf /tmp/atri_test_safe_delete_me_please` and confirm it worked.",
     "bash_exec", "Bash exec of safe delete"),
    ("E03", "edge",
     "What is the square root of -1? Then list files in /tmp/.",
     "list_directory", "Mixed: math + tool call"),

    # ── Instruction following ─────────────────────────────────────────────────
    ("I01", "instruction",
     "Reply with ONLY the word 'pong' and nothing else.",
     None, "Strict instruction following — no tools, exact output"),
]


# ── Runner ────────────────────────────────────────────────────────────────────

@dataclass
class TestResult:
    id: str
    category: str
    description: str
    prompt: str
    expected_tool: str | None
    status: str = "pending"       # pending | pass | fail | error | timeout
    tools_called: list[str] = field(default_factory=list)
    tool_called_expected: bool = False
    response_text: str = ""
    error: str = ""
    latency_s: float = 0.0
    raw_events: list[dict] = field(default_factory=list)


def _parse_sse(raw: str) -> list[dict]:
    """Parse Server-Sent Events text into a list of event dicts."""
    events = []
    for line in raw.splitlines():
        if line.startswith("data: "):
            payload = line[6:].strip()
            if payload and payload != "[DONE]":
                try:
                    events.append(json.loads(payload))
                except json.JSONDecodeError:
                    events.append({"raw": payload})
    return events


async def run_prompt(client: httpx.AsyncClient, entry: tuple) -> TestResult:
    pid, category, prompt, expected_tool, desc = entry
    result = TestResult(
        id=pid, category=category, description=desc,
        prompt=prompt, expected_tool=expected_tool
    )

    body = {
        "message": prompt,
        "session_id": f"harness-{pid.lower()}",
        "stream": False,
    }

    t0 = time.perf_counter()
    try:
        resp = await client.post(
            f"{BASE_URL}/chat/stream",
            json=body,
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        result.latency_s = time.perf_counter() - t0

        if resp.status_code != 200:
            result.status = "error"
            result.error = f"HTTP {resp.status_code}: {resp.text[:300]}"
            return result

        content_type = resp.headers.get("content-type", "")
        raw = resp.text

        if "text/event-stream" in content_type or raw.startswith("data:"):
            events = _parse_sse(raw)
        else:
            try:
                events = [resp.json()]
            except Exception:
                events = [{"raw": raw}]

        result.raw_events = events

        # SSE format:
        #   {"type": "assistant_delta", "content": "..."} — final response chunks
        #   {"type": "agent_event", "event": {"type": "tool_call_start", "tool_name": "..."}}
        #   {"type": "agent_event", "event": {"type": "tool_call_result", "tool_name": "..."}}
        for ev in events:
            etype = ev.get("type", "")

            # Final response text
            if etype == "assistant_delta":
                result.response_text += ev.get("content", "")

            # Tool call events wrapped inside agent_event
            elif etype == "agent_event":
                inner = ev.get("event", {})
                itype = inner.get("type", "")
                if itype == "tool_call_start":
                    result.tools_called.append(inner.get("tool_name", "unknown"))
                elif itype == "tool_call_result":
                    # tool succeeded — already recorded at start
                    pass

        # Deduplicate tools list
        result.tools_called = list(dict.fromkeys(result.tools_called))

        # Evaluate
        if expected_tool:
            result.tool_called_expected = expected_tool in result.tools_called
            result.status = "pass" if result.tool_called_expected else "fail"
        else:
            result.status = "pass" if result.response_text.strip() else "fail"

    except httpx.TimeoutException:
        result.latency_s = time.perf_counter() - t0
        result.status = "timeout"
        result.error = f"Timed out after {TIMEOUT}s"
    except Exception as exc:
        result.latency_s = time.perf_counter() - t0
        result.status = "error"
        result.error = str(exc)

    return result


async def run_all() -> list[TestResult]:
    results = []
    async with httpx.AsyncClient() as client:
        # Run sequentially to avoid overwhelming the model (single-threaded inference)
        for entry in PROMPTS:
            pid = entry[0]
            print(f"  [{pid}] {entry[4][:55]:<55} ", end="", flush=True)
            r = await run_prompt(client, entry)
            icon = {"pass": "✓", "fail": "✗", "error": "E", "timeout": "T"}.get(r.status, "?")
            tools_str = f" tools={r.tools_called}" if r.tools_called else ""
            print(f"{icon}  {r.latency_s:5.1f}s{tools_str}")
            results.append(r)
    return results


def print_report(results: list[TestResult]):
    total     = len(results)
    passed    = sum(1 for r in results if r.status == "pass")
    failed    = sum(1 for r in results if r.status == "fail")
    errors    = sum(1 for r in results if r.status == "error")
    timeouts  = sum(1 for r in results if r.status == "timeout")

    tool_tests    = [r for r in results if r.expected_tool]
    tool_pass     = sum(1 for r in tool_tests if r.tool_called_expected)
    tool_rate     = tool_pass / len(tool_tests) * 100 if tool_tests else 0

    avg_latency = sum(r.latency_s for r in results) / total if total else 0

    print("\n" + "═" * 70)
    print("ATRI HARNESS REPORT")
    print("═" * 70)
    print(f"Total: {total}  Pass: {passed}  Fail: {failed}  Error: {errors}  Timeout: {timeouts}")
    print(f"Tool call rate: {tool_pass}/{len(tool_tests)} = {tool_rate:.0f}%")
    print(f"Avg latency: {avg_latency:.1f}s")
    print()

    # Per-category breakdown
    cats: dict[str, list[TestResult]] = {}
    for r in results:
        cats.setdefault(r.category, []).append(r)
    print(f"{'Category':<14} {'Pass':>4} {'Fail':>4} {'Err':>3} {'T/O':>3} {'Avg(s)':>7}")
    print("-" * 40)
    for cat, rs in sorted(cats.items()):
        cp = sum(1 for x in rs if x.status == "pass")
        cf = sum(1 for x in rs if x.status == "fail")
        ce = sum(1 for x in rs if x.status == "error")
        ct = sum(1 for x in rs if x.status == "timeout")
        al = sum(x.latency_s for x in rs) / len(rs)
        print(f"  {cat:<12} {cp:>4} {cf:>4} {ce:>3} {ct:>3} {al:>7.1f}")
    print()

    # Failures detail
    failures = [r for r in results if r.status != "pass"]
    if failures:
        print("── FAILURES / ERRORS ────────────────────────────────────────────────")
        for r in failures:
            print(f"\n  [{r.id}] {r.status.upper()} — {r.description}")
            print(f"    Prompt:   {r.prompt[:90]}")
            if r.expected_tool:
                print(f"    Expected tool: {r.expected_tool}")
                print(f"    Got tools:     {r.tools_called or 'none'}")
            if r.error:
                print(f"    Error: {r.error[:200]}")
            if r.response_text:
                print(f"    Response: {r.response_text[:200]}")

    # Successful tool calls
    tool_wins = [r for r in results if r.tool_called_expected]
    if tool_wins:
        print("\n── SUCCESSFUL TOOL CALLS ────────────────────────────────────────────")
        for r in tool_wins:
            print(f"  [{r.id}] {r.expected_tool} → {r.tools_called}  ({r.latency_s:.1f}s)")
            print(f"         {r.response_text[:150]!r}")

    print("\n── SAMPLE RESPONSES (knowledge / instruction) ───────────────────────")
    for r in results:
        if r.category in ("knowledge", "instruction") and r.status == "pass":
            print(f"  [{r.id}] {r.response_text[:200]!r}")

    # Diagnose
    print("\n── DIAGNOSIS ────────────────────────────────────────────────────────")
    if tool_rate == 0:
        print("  CRITICAL: 0% tool call rate — model ignores tool-call format.")
        print("  → Check that prompt_policy.py has <|tool_call> examples in active profile.")
        print("  → Confirm PROMPT_POLICY_DEFAULT_PROFILE=agent-v3 in .env")
    elif tool_rate < 50:
        print(f"  WARNING: low tool call rate ({tool_rate:.0f}%). Model inconsistently uses tools.")
        print("  → Review which categories fail; add more few-shot examples for those tool types.")
    else:
        print(f"  Tool calling looks healthy ({tool_rate:.0f}%).")

    slow = [r for r in results if r.latency_s > 45]
    if slow:
        print(f"  SLOW: {len(slow)} prompts took >45s: {[r.id for r in slow]}")

    no_response = [r for r in results if not r.response_text and r.status != "error"]
    if no_response:
        print(f"  EMPTY RESPONSES: {[r.id for r in no_response]}")

    print()


def main():
    print(f"Atri Harness — {len(PROMPTS)} prompts → {BASE_URL}")
    print(f"API key: {'set' if API_KEY else 'NOT SET'}")
    print()

    # Health check
    import urllib.request, urllib.error
    try:
        urllib.request.urlopen(f"{BASE_URL}/health", timeout=5)
        print("Orchestrator: healthy ✓\n")
    except Exception as e:
        print(f"Orchestrator unreachable: {e}")
        print("Start services with:  make cli-up")
        sys.exit(1)

    results = asyncio.run(run_all())
    print_report(results)

    # Write JSON report
    report_path = "tests/harness_report.json"
    with open(report_path, "w") as f:
        json.dump([
            {
                "id": r.id,
                "category": r.category,
                "description": r.description,
                "status": r.status,
                "expected_tool": r.expected_tool,
                "tools_called": r.tools_called,
                "tool_called_expected": r.tool_called_expected,
                "latency_s": round(r.latency_s, 2),
                "response_text": r.response_text[:500],
                "error": r.error,
            }
            for r in results
        ], f, indent=2)
    print(f"JSON report → {report_path}")


if __name__ == "__main__":
    main()
