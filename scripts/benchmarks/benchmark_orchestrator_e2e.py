#!/usr/bin/env python3
"""End-to-end benchmark for the orchestrator service.

This script validates and benchmarks:
- orchestrator health and service readiness
- direct /chat request-response path
- direct /chat/stream SSE path

It is intended for live integration runs against a running stack.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class BenchmarkResult:
    name: str
    passed: bool
    latency_ms: float
    details: dict[str, Any]


def _headers(token: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _request_json(
    method: str,
    base_url: str,
    path: str,
    token: str | None,
    payload: dict[str, Any] | None = None,
    timeout: float = 60.0,
) -> tuple[int, dict[str, Any], float]:
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url, data=data, method=method, headers=_headers(token))
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            body = json.loads(raw) if raw else {}
            return resp.status, body, elapsed_ms
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        try:
            body = json.loads(raw) if raw else {}
        except Exception:
            body = {"raw": raw}
        return exc.code, body, elapsed_ms


def _stream_chat(
    base_url: str,
    token: str | None,
    payload: dict[str, Any],
    timeout: float,
) -> tuple[int, dict[str, Any], float]:
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", "chat/stream")
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers=_headers(token),
    )

    first_chunk_ms = None
    chunk_count = 0
    content_parts: list[str] = []
    request_id = ""

    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break

                if first_chunk_ms is None:
                    first_chunk_ms = (time.perf_counter() - start) * 1000.0

                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue

                if "request_id" in event:
                    request_id = str(event["request_id"])
                if "content" in event and event["content"]:
                    content_parts.append(str(event["content"]))
                    chunk_count += 1
                if "error" in event:
                    return resp.status, {
                        "error": event["error"],
                        "request_id": request_id,
                    }, (time.perf_counter() - start) * 1000.0

            total_ms = (time.perf_counter() - start) * 1000.0
            return resp.status, {
                "response": "".join(content_parts).strip(),
                "request_id": request_id,
                "chunks": chunk_count,
                "first_chunk_ms": round(first_chunk_ms or total_ms, 2),
            }, total_ms
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return exc.code, {"error": raw}, (time.perf_counter() - start) * 1000.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark orchestrator end-to-end path")
    parser.add_argument("--base-url", default=os.getenv("ORCHESTRATOR_BENCH_BASE_URL", "http://127.0.0.1:8001"))
    parser.add_argument("--auth-token", default=os.getenv("ORCHESTRATOR_BENCH_AUTH_TOKEN"))
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--allowed-directory", default=str(Path.cwd()))
    parser.add_argument(
        "--require-stream-endpoint",
        action="store_true",
        help="Fail benchmark when /chat/stream is unavailable",
    )
    args = parser.parse_args()

    checks: list[BenchmarkResult] = []

    status, health, latency = _request_json("GET", args.base_url, "/health", args.auth_token, timeout=args.timeout)
    checks.append(
        BenchmarkResult(
            name="health_check",
            passed=status == 200 and bool(health.get("llm_connected")),
            latency_ms=latency,
            details={"status": status, "payload": health},
        )
    )

    status, tools, latency = _request_json("GET", args.base_url, "/tools", args.auth_token, timeout=args.timeout)
    checks.append(
        BenchmarkResult(
            name="tools_endpoint",
            passed=status == 200 and isinstance(tools.get("tools"), list),
            latency_ms=latency,
            details={"status": status, "total": tools.get("total")},
        )
    )

    prompt_set = [
        "Say hello in one short sentence.",
        "List two reasons to use an orchestrator for tool-calling models.",
        "What should we verify in an end-to-end benchmark for this system?",
    ]

    chat_latencies = []
    for index in range(min(args.iterations, len(prompt_set))):
        payload = {
            "message": prompt_set[index],
            "allowed_directory": args.allowed_directory,
        }
        status, body, latency = _request_json(
            "POST", args.base_url, "/chat", args.auth_token, payload=payload, timeout=args.timeout
        )
        passed = (
            status == 200
            and isinstance(body.get("response"), str)
            and bool(body.get("response", "").strip())
            and isinstance(body.get("conversation_id"), str)
        )
        chat_latencies.append(latency)
        checks.append(
            BenchmarkResult(
                name=f"chat_round_{index + 1}",
                passed=passed,
                latency_ms=latency,
                details={
                    "status": status,
                    "conversation_id": body.get("conversation_id"),
                    "turns": body.get("turns"),
                    "tool_calls": body.get("tool_calls"),
                    "request_id": body.get("request_id"),
                },
            )
        )

    stream_payload = {
        "message": "Provide a concise statement confirming stream response generation.",
        "allowed_directory": args.allowed_directory,
    }
    status, stream_data, total_stream_ms = _stream_chat(
        args.base_url,
        args.auth_token,
        payload=stream_payload,
        timeout=args.timeout,
    )
    stream_ok = (
        status == 200
        and isinstance(stream_data.get("response"), str)
        and bool(stream_data.get("response", "").strip())
        and int(stream_data.get("chunks", 0)) > 0
    )

    if not stream_ok and status == 404 and not args.require_stream_endpoint:
        fallback_status, fallback_body, fallback_ms = _request_json(
            "POST",
            args.base_url,
            "/chat",
            args.auth_token,
            payload=stream_payload,
            timeout=args.timeout,
        )
        stream_ok = (
            fallback_status == 200
            and isinstance(fallback_body.get("response"), str)
            and bool(fallback_body.get("response", "").strip())
        )
        checks.append(
            BenchmarkResult(
                name="chat_stream_compatibility",
                passed=stream_ok,
                latency_ms=fallback_ms,
                details={
                    "status": status,
                    "fallback_status": fallback_status,
                    "mode": "fallback_to_chat",
                    "note": "stream endpoint unavailable on running instance",
                },
            )
        )
    else:
        checks.append(
            BenchmarkResult(
                name="chat_stream",
                passed=stream_ok,
                latency_ms=total_stream_ms,
                details={
                    "status": status,
                    "request_id": stream_data.get("request_id"),
                    "chunks": stream_data.get("chunks"),
                    "first_chunk_ms": stream_data.get("first_chunk_ms"),
                    "error": stream_data.get("error"),
                },
            )
        )

    passed = all(item.passed for item in checks)
    average_chat_ms = round(statistics.mean(chat_latencies), 2) if chat_latencies else None

    report = {
        "benchmark": "orchestrator_e2e",
        "base_url": args.base_url,
        "passed": passed,
        "results": [
            {
                "name": item.name,
                "passed": item.passed,
                "latency_ms": round(item.latency_ms, 2),
                "details": item.details,
            }
            for item in checks
        ],
        "summary": {
            "average_chat_latency_ms": average_chat_ms,
            "total_checks": len(checks),
            "passed_checks": sum(1 for item in checks if item.passed),
        },
    }

    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
