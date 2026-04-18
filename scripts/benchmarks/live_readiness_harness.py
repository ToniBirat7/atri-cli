#!/usr/bin/env python3
"""Live readiness harness for CLI + web + orchestrator pipelines.

This script boots the orchestrator, optionally boots frontend, runs smoke checks,
measures MCP tool-call success rates from streamed events, and emits a readiness
scorecard JSON report.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional
import threading


@dataclass
class CheckResult:
    name: str
    passed: bool
    latency_ms: float
    details: dict[str, Any]


def _request(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> tuple[int, str, float]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers=headers or {"Content-Type": "application/json"},
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            elapsed = (time.perf_counter() - start) * 1000.0
            return response.status, text, elapsed
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        elapsed = (time.perf_counter() - start) * 1000.0
        return exc.code, text, elapsed
    except urllib.error.URLError as exc:
        elapsed = (time.perf_counter() - start) * 1000.0
        return 0, str(exc), elapsed


def _wait_for_url(
    url: str,
    timeout_seconds: float,
    process: Optional[subprocess.Popen[str]] = None,
) -> tuple[bool, float]:
    started = time.perf_counter()
    deadline = started + timeout_seconds
    while time.perf_counter() < deadline:
        if process is not None and process.poll() is not None:
            return False, (time.perf_counter() - started) * 1000.0
        status, _, _ = _request("GET", url, timeout=5.0)
        if status in {200, 503}:
            return True, (time.perf_counter() - started) * 1000.0
        time.sleep(0.2)
    return False, (time.perf_counter() - started) * 1000.0


def _read_process_excerpt(proc: Optional[subprocess.Popen[str]], max_chars: int = 1200) -> str:
    if proc is None:
        return ""
    if proc.poll() is None:
        return ""
    try:
        stderr = proc.stderr.read() if proc.stderr else ""
    except Exception:
        stderr = ""
    if not stderr:
        return ""
    return stderr[-max_chars:]


def _stream_chat(base_url: str, message: str, allowed_directory: str, timeout: float) -> tuple[int, dict[str, Any], float]:
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", "chat/stream")
    payload = {
        "message": message,
        "allowed_directory": allowed_directory,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    start = time.perf_counter()
    content_parts: list[str] = []
    tool_ok = 0
    tool_error = 0
    usage_prompt_tokens = 0
    usage_completion_tokens = 0
    usage_total_tokens = 0

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    parsed = json.loads(data)
                except json.JSONDecodeError:
                    continue

                if parsed.get("content"):
                    content_parts.append(str(parsed["content"]))

                event = parsed.get("event")
                if isinstance(event, dict):
                    event_type = str(event.get("type") or "")
                    if event_type == "tool_call_result":
                        if str(event.get("status") or "") == "ok":
                            tool_ok += 1
                        else:
                            tool_error += 1
                    if event_type == "usage":
                        usage_prompt_tokens += int(event.get("prompt_tokens") or 0)
                        usage_completion_tokens += int(event.get("completion_tokens") or 0)
                        usage_total_tokens += int(event.get("total_tokens") or 0)

                if parsed.get("error"):
                    total_ms = (time.perf_counter() - start) * 1000.0
                    return resp.status, {
                        "error": parsed.get("error"),
                        "tool_ok": tool_ok,
                        "tool_error": tool_error,
                        "usage_prompt_tokens": usage_prompt_tokens,
                        "usage_completion_tokens": usage_completion_tokens,
                        "usage_total_tokens": usage_total_tokens,
                    }, total_ms

        total_ms = (time.perf_counter() - start) * 1000.0
        return resp.status, {
            "response": "".join(content_parts).strip(),
            "tool_ok": tool_ok,
            "tool_error": tool_error,
            "usage_prompt_tokens": usage_prompt_tokens,
            "usage_completion_tokens": usage_completion_tokens,
            "usage_total_tokens": usage_total_tokens,
        }, total_ms
    except urllib.error.HTTPError as exc:
        total_ms = (time.perf_counter() - start) * 1000.0
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, {"error": body}, total_ms
    except urllib.error.URLError as exc:
        total_ms = (time.perf_counter() - start) * 1000.0
        return 0, {"error": str(exc)}, total_ms


def _run_command(command: list[str], cwd: Path, env: dict[str, str], timeout: float) -> tuple[int, str, str, float]:
    start = time.perf_counter()
    proc = subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        timeout=timeout,
        capture_output=True,
        text=True,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return proc.returncode, proc.stdout, proc.stderr, elapsed_ms


def _terminate_process(proc: Optional[subprocess.Popen[str]]) -> None:
    if proc is None:
        return
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def _start_stub_llm_server() -> tuple[ThreadingHTTPServer, threading.Thread, str]:
    state = {"request_count": 0}

    class StubHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def _write_json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path in {"/health", "/v1/models"}:
                if self.path == "/health":
                    self._write_json({"status": "ok"})
                else:
                    self._write_json({"object": "list", "data": [{"id": "stub-model", "object": "model"}]})
                return
            self._write_json({"error": "not found"}, status=404)

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/chat/completions":
                self._write_json({"error": "not found"}, status=404)
                return

            length = int(self.headers.get("Content-Length") or "0")
            body = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                payload = {}

            state["request_count"] += 1
            request_count = state["request_count"]
            messages = payload.get("messages") or []
            user_message = next(
                (str(message.get("content") or "") for message in reversed(messages) if message.get("role") == "user"),
                "",
            )

            if request_count == 1:
                response = {
                    "id": "chatcmpl-stub-1",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": payload.get("model") or "stub-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call_stub_1",
                                        "type": "function",
                                        "function": {
                                            "name": "list_directory",
                                            "arguments": json.dumps({"path": "."}),
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": max(32, len(user_message.split()) * 2),
                        "completion_tokens": 12,
                        "total_tokens": max(44, len(user_message.split()) * 2 + 12),
                    },
                }
            else:
                response = {
                    "id": f"chatcmpl-stub-{request_count}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": payload.get("model") or "stub-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "Directory listing completed successfully.",
                                "tool_calls": [],
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 24,
                        "completion_tokens": 10,
                        "total_tokens": 34,
                    },
                }

            self._write_json(response)

    server = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_port}/v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live readiness harness for orchestrator + CLI + web")
    parser.add_argument("--workspace", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--python", default=str(Path(__file__).resolve().parents[2] / ".env" / "bin" / "python"))
    parser.add_argument("--orchestrator-url", default="http://127.0.0.1:8001")
    parser.add_argument("--frontend-url", default="http://127.0.0.1:3000")
    parser.add_argument("--frontend-port", type=int, default=3000)
    parser.add_argument("--start-frontend", action="store_true")
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--report-file", default="")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    python_exe = Path(args.python)
    uvicorn_executable = python_exe.parent / "uvicorn"
    orchestrator_dir = workspace / "services" / "orchestrator"
    frontend_dir = workspace / "apps" / "frontend"

    checks: list[CheckResult] = []
    orchestrator_proc: Optional[subprocess.Popen[str]] = None
    frontend_proc: Optional[subprocess.Popen[str]] = None
    llm_stub_server: Optional[ThreadingHTTPServer] = None
    llm_backend_mode = "real"
    llm_base_url = os.getenv("LLM_BENCH_BASE_URL", "http://127.0.0.1:8000/v1")

    status, _, _ = _request("GET", urllib.parse.urljoin(llm_base_url.rstrip("/") + "/", "models"), timeout=5.0)
    if status != 200:
        llm_stub_server, _, llm_base_url = _start_stub_llm_server()
        llm_backend_mode = "stub"

    try:
        orchestrator_env = os.environ.copy()
        orchestrator_env["PYTHONPATH"] = (
            f"{workspace / 'services' / 'orchestrator'}:{workspace / 'services' / 'mcp'}"
        )
        orchestrator_env["LLM_BASE_URL"] = llm_base_url
        orchestrator_env.setdefault("LLM_API_KEY", "secret")

        if uvicorn_executable.exists():
            orchestrator_command = [
                str(uvicorn_executable),
                "api:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8001",
            ]
        else:
            orchestrator_command = [
                str(python_exe),
                "-m",
                "uvicorn",
                "api:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8001",
            ]

        orchestrator_proc = subprocess.Popen(
            orchestrator_command,
            cwd=str(orchestrator_dir),
            env=orchestrator_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        ready_ok, ready_wait_ms = _wait_for_url(
            urllib.parse.urljoin(args.orchestrator_url.rstrip("/") + "/", "ready"),
            timeout_seconds=45.0,
            process=orchestrator_proc,
        )

        boot_details: dict[str, Any] = {"pid": orchestrator_proc.pid if orchestrator_proc else None}
        if not ready_ok:
            boot_details["exit_code"] = orchestrator_proc.poll() if orchestrator_proc else None
            excerpt = _read_process_excerpt(orchestrator_proc)
            if excerpt:
                boot_details["stderr_excerpt"] = excerpt

        checks.append(
            CheckResult(
                name="orchestrator_boot",
                passed=ready_ok,
                latency_ms=ready_wait_ms,
                details=boot_details,
            )
        )

        if args.start_frontend:
            frontend_env = os.environ.copy()
            frontend_env["PORT"] = str(args.frontend_port)
            frontend_proc = subprocess.Popen(
                ["npm", "run", "start", "--", "--port", str(args.frontend_port)],
                cwd=str(frontend_dir),
                env=frontend_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            frontend_ok, frontend_wait_ms = _wait_for_url(args.frontend_url, timeout_seconds=45.0)
            checks.append(
                CheckResult(
                    name="frontend_boot",
                    passed=frontend_ok,
                    latency_ms=frontend_wait_ms,
                    details={"pid": frontend_proc.pid if frontend_proc else None},
                )
            )

        status, health_text, latency_ms = _request(
            "GET",
            urllib.parse.urljoin(args.orchestrator_url.rstrip("/") + "/", "health"),
            timeout=15.0,
        )
        try:
            health = json.loads(health_text)
        except Exception:
            health = {"raw": health_text}
        checks.append(
            CheckResult(
                name="orchestrator_health",
                passed=status == 200,
                latency_ms=latency_ms,
                details={"status": status, "payload": health},
            )
        )

        status, tools_text, latency_ms = _request(
            "GET",
            urllib.parse.urljoin(args.orchestrator_url.rstrip("/") + "/", "tools"),
            timeout=15.0,
        )
        try:
            tools = json.loads(tools_text)
        except Exception:
            tools = {"raw": tools_text}
        checks.append(
            CheckResult(
                name="orchestrator_tools",
                passed=status == 200 and int(tools.get("total", 0)) > 0,
                latency_ms=latency_ms,
                details={"status": status, "total": tools.get("total")},
            )
        )

        cli_env = os.environ.copy()
        cli_env["PYTHONPATH"] = f"{workspace / 'apps' / 'cli'}"

        rc, out, err, elapsed = _run_command(
            [
                str(python_exe),
                "-m",
                "tarbar_cli.main",
                "--api-url",
                args.orchestrator_url,
                "mcp",
                "status",
            ],
            cwd=workspace,
            env=cli_env,
            timeout=args.timeout,
        )
        checks.append(
            CheckResult(
                name="cli_mcp_status",
                passed=rc == 0 and "Status:" in out,
                latency_ms=elapsed,
                details={"exit_code": rc, "stderr": err[:300]},
            )
        )

        rc, out, err, elapsed = _run_command(
            [
                str(python_exe),
                "-m",
                "tarbar_cli.main",
                "--api-url",
                args.orchestrator_url,
                "mcp",
                "tools",
            ],
            cwd=workspace,
            env=cli_env,
            timeout=args.timeout,
        )
        checks.append(
            CheckResult(
                name="cli_mcp_tools",
                passed=rc == 0 and "Available tools" in out,
                latency_ms=elapsed,
                details={"exit_code": rc, "stderr": err[:300]},
            )
        )

        tool_ok_total = 0
        tool_error_total = 0
        usage_events_seen = 0
        for idx in range(max(1, args.iterations)):
            status, stream_data, elapsed = _stream_chat(
                args.orchestrator_url,
                message="List top entries in the current directory using tools and keep it concise.",
                allowed_directory=str(workspace),
                timeout=args.timeout,
            )
            tool_ok_total += int(stream_data.get("tool_ok") or 0)
            tool_error_total += int(stream_data.get("tool_error") or 0)
            if int(stream_data.get("usage_total_tokens") or 0) > 0:
                usage_events_seen += 1
            checks.append(
                CheckResult(
                    name=f"stream_round_{idx + 1}",
                    passed=status == 200 and not stream_data.get("error"),
                    latency_ms=elapsed,
                    details={
                        "status": status,
                        "tool_ok": stream_data.get("tool_ok", 0),
                        "tool_error": stream_data.get("tool_error", 0),
                        "usage_total_tokens": stream_data.get("usage_total_tokens", 0),
                        "error": stream_data.get("error"),
                    },
                )
            )

        tool_total = tool_ok_total + tool_error_total
        tool_success_rate = (tool_ok_total / tool_total) if tool_total > 0 else None
        checks.append(
            CheckResult(
                name="mcp_tool_call_success_rate",
                passed=(tool_success_rate is not None and tool_success_rate >= 0.95),
                latency_ms=0.0,
                details={
                    "tool_ok_total": tool_ok_total,
                    "tool_error_total": tool_error_total,
                    "tool_success_rate": tool_success_rate,
                    "observed_tool_calls": tool_total,
                },
            )
        )

        checks.append(
            CheckResult(
                name="usage_events_present",
                passed=usage_events_seen > 0,
                latency_ms=0.0,
                details={"rounds_with_usage_events": usage_events_seen},
            )
        )

        if args.start_frontend:
            status, body, elapsed = _request("GET", args.frontend_url, timeout=15.0)
            checks.append(
                CheckResult(
                    name="web_root",
                    passed=status == 200 and "<html" in body.lower(),
                    latency_ms=elapsed,
                    details={"status": status},
                )
            )

            status, body, elapsed = _request(
                "POST",
                urllib.parse.urljoin(args.frontend_url.rstrip("/") + "/", "api/validate-directory"),
                payload={"path": str(workspace)},
                timeout=20.0,
            )
            try:
                validate_payload = json.loads(body)
            except Exception:
                validate_payload = {"raw": body}
            checks.append(
                CheckResult(
                    name="web_validate_directory",
                    passed=status == 200 and bool(validate_payload.get("ok")),
                    latency_ms=elapsed,
                    details={"status": status, "payload": validate_payload},
                )
            )

        passed_checks = sum(1 for check in checks if check.passed)
        total_checks = len(checks)
        readiness_score = round((passed_checks / total_checks) * 100.0, 2) if total_checks else 0.0

        report = {
            "harness": "live_readiness_harness",
            "timestamp": int(time.time()),
            "workspace": str(workspace),
            "orchestrator_url": args.orchestrator_url,
            "frontend_url": args.frontend_url,
            "start_frontend": args.start_frontend,
            "llm_backend_mode": llm_backend_mode,
            "llm_backend_url": llm_base_url,
            "summary": {
                "readiness_score": readiness_score,
                "total_checks": total_checks,
                "passed_checks": passed_checks,
                "failed_checks": total_checks - passed_checks,
            },
            "results": [asdict(item) for item in checks],
        }

        rendered = json.dumps(report, indent=2, ensure_ascii=True)
        print(rendered)
        if args.report_file:
            Path(args.report_file).write_text(rendered + "\n", encoding="utf-8")

        return 0 if readiness_score >= 80.0 else 1
    finally:
        _terminate_process(frontend_proc)
        _terminate_process(orchestrator_proc)
        if llm_stub_server is not None:
            llm_stub_server.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
