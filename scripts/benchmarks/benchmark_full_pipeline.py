#!/usr/bin/env python3
"""Full pipeline benchmark from frontend query to final response.

Pipeline covered:
frontend /api/chat -> orchestrator /chat/stream -> llama.cpp (+ MCP if invoked)
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
class PipelineCheck:
    name: str
    passed: bool
    latency_ms: float
    details: dict[str, Any]


def _request(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> tuple[int, str, float]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers=headers or {"Content-Type": "application/json"},
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return resp.status, text, (time.perf_counter() - start) * 1000.0
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return exc.code, text, (time.perf_counter() - start) * 1000.0


def _stream_frontend_chat(
    frontend_url: str,
    payload: dict[str, Any],
    timeout: float,
) -> tuple[int, dict[str, Any], float]:
    url = urllib.parse.urljoin(frontend_url.rstrip("/") + "/", "api/chat")
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    response_parts: list[str] = []
    chunk_count = 0
    first_chunk_ms = None
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
                if event.get("content"):
                    response_parts.append(str(event["content"]))
                    chunk_count += 1
                if event.get("error"):
                    return resp.status, {
                        "error": event["error"],
                        "chunks": chunk_count,
                        "first_chunk_ms": round(first_chunk_ms or 0.0, 2),
                    }, (time.perf_counter() - start) * 1000.0

            total_ms = (time.perf_counter() - start) * 1000.0
            return resp.status, {
                "response": "".join(response_parts).strip(),
                "chunks": chunk_count,
                "first_chunk_ms": round(first_chunk_ms or total_ms, 2),
            }, total_ms
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return exc.code, {"error": text}, (time.perf_counter() - start) * 1000.0


def _direct_orchestrator_chat(
    orchestrator_url: str,
    message: str,
    allowed_directory: str,
    timeout: float,
) -> tuple[int, dict[str, Any], float]:
    url = urllib.parse.urljoin(orchestrator_url.rstrip("/") + "/", "chat")
    payload = {
        "message": message,
        "allowed_directory": allowed_directory,
    }
    status, text, elapsed_ms = _request("POST", url, payload=payload, timeout=timeout)
    try:
        body = json.loads(text)
    except Exception:
        body = {"raw": text}
    return status, body, elapsed_ms


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark complete frontend-to-model pipeline")
    parser.add_argument("--frontend-url", default=os.getenv("FRONTEND_BENCH_BASE_URL", "http://127.0.0.1:3000"))
    parser.add_argument("--orchestrator-url", default=os.getenv("ORCHESTRATOR_BENCH_BASE_URL", "http://127.0.0.1:8001"))
    parser.add_argument("--llm-url", default=os.getenv("LLM_BENCH_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--llm-api-key", default=os.getenv("LLM_BENCH_API_KEY", "secret"))
    parser.add_argument("--prompt-profile", default=os.getenv("BENCH_PROMPT_PROFILE", "general-purpose"))
    parser.add_argument("--allowed-directory", default=str(Path.cwd()))
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    checks: list[PipelineCheck] = []

    llm_models_url = urllib.parse.urljoin(args.llm_url.rstrip("/") + "/", "v1/models")
    llm_headers = {
        "Authorization": f"Bearer {args.llm_api_key}",
        "Content-Type": "application/json",
    }
    status, text, latency = _request("GET", llm_models_url, headers=llm_headers, timeout=args.timeout)
    llm_ok = False
    try:
        payload = json.loads(text)
        llm_ok = status == 200 and bool(payload.get("data") or payload.get("models"))
    except Exception:
        payload = {"raw": text}
    checks.append(
        PipelineCheck(
            name="llm_models",
            passed=llm_ok,
            latency_ms=latency,
            details={"status": status},
        )
    )

    orch_health_url = urllib.parse.urljoin(args.orchestrator_url.rstrip("/") + "/", "health")
    status, text, latency = _request("GET", orch_health_url, timeout=args.timeout)
    orch_ok = False
    try:
        payload = json.loads(text)
        orch_ok = status == 200 and bool(payload.get("llm_connected"))
    except Exception:
        payload = {"raw": text}
    checks.append(
        PipelineCheck(
            name="orchestrator_health",
            passed=orch_ok,
            latency_ms=latency,
            details={"status": status, "payload": payload},
        )
    )

    frontend_root = urllib.parse.urljoin(args.frontend_url.rstrip("/") + "/", "")
    status, text, latency = _request("GET", frontend_root, timeout=args.timeout)
    checks.append(
        PipelineCheck(
            name="frontend_root",
            passed=status == 200 and "<html" in text.lower(),
            latency_ms=latency,
            details={"status": status},
        )
    )

    prompts = [
        "Give one line describing the purpose of this stack.",
        "List two checks a production benchmark should include.",
        "Provide one sentence confirming end-to-end response path health.",
    ]

    latencies: list[float] = []
    for i in range(min(args.iterations, len(prompts))):
        payload = {
            "messages": [{"role": "user", "content": prompts[i]}],
            "allowedDirectory": args.allowed_directory,
            "promptProfile": args.prompt_profile,
        }
        status, stream_data, elapsed_ms = _stream_frontend_chat(
            args.frontend_url,
            payload=payload,
            timeout=args.timeout,
        )
        passed = (
            status == 200
            and isinstance(stream_data.get("response"), str)
            and bool(stream_data.get("response", "").strip())
            and int(stream_data.get("chunks", 0)) > 0
            and not stream_data.get("error")
        )
        latencies.append(elapsed_ms)
        checks.append(
            PipelineCheck(
                name=f"frontend_stream_round_{i + 1}",
                passed=passed,
                latency_ms=elapsed_ms,
                details={
                    "status": status,
                    "chunks": stream_data.get("chunks"),
                    "first_chunk_ms": stream_data.get("first_chunk_ms"),
                    "error": stream_data.get("error"),
                },
            )
        )

        if (not passed) and status == 404 and "Not Found" in str(stream_data.get("error", "")):
            fallback_status, fallback_body, fallback_ms = _direct_orchestrator_chat(
                orchestrator_url=args.orchestrator_url,
                message=prompts[i],
                allowed_directory=args.allowed_directory,
                timeout=args.timeout,
            )
            fallback_ok = (
                fallback_status == 200
                and isinstance(fallback_body.get("response"), str)
                and bool(fallback_body.get("response", "").strip())
            )
            checks.append(
                PipelineCheck(
                    name=f"frontend_proxy_compatibility_round_{i + 1}",
                    passed=fallback_ok,
                    latency_ms=fallback_ms,
                    details={
                        "frontend_status": status,
                        "fallback_status": fallback_status,
                        "note": "frontend stream failed because upstream /chat/stream is unavailable",
                    },
                )
            )

    passed = all(item.passed for item in checks)
    report = {
        "benchmark": "full_pipeline",
        "frontend_url": args.frontend_url,
        "orchestrator_url": args.orchestrator_url,
        "llm_url": args.llm_url,
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
            "average_pipeline_latency_ms": round(statistics.mean(latencies), 2) if latencies else None,
            "total_checks": len(checks),
            "passed_checks": sum(1 for item in checks if item.passed),
        },
    }
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
