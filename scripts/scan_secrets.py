#!/usr/bin/env python3
"""Lightweight secret scanner for tracked files.

This script is intentionally conservative: it blocks obvious secrets while
allowing known placeholder values used in docs/examples.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIP_PATH_PREFIXES = {
    "runtime/llm/llama.cpp/",
}

ALLOWED_VALUES = {
    "",
    "secret",
    "your-secret-key",
    "change-me-in-production",
    "replace-with-a-long-random-secret",
    "replace-me",
    "__set_me__",
}

ALLOWED_VALUE_MARKERS = {
    "test",
    "dummy",
    "example",
    "your",
    "sample",
    "placeholder",
}

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf", ".zip",
    ".tar", ".gz", ".woff", ".woff2", ".ttf", ".eot", ".ico", ".db",
}

PATTERNS = [
    ("tavily_api_key", re.compile(r"\btvly-[A-Za-z0-9-]{20,}\b")),
    ("openai_style_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("private_key_header", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    (
        "generic_assignment",
        re.compile(
            r"(?i)\b(api[_-]?key|secret|token|password|jwt[_-]?secret)\b\s*[:=]\s*['\"]([A-Za-z0-9_\-]{8,})['\"]"
        ),
    ),
]


def _git_tracked_files() -> list[Path]:
    proc = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "git ls-files failed").strip())

    result: list[Path] = []
    for line in proc.stdout.splitlines():
        rel = line.strip()
        if any(rel.startswith(prefix) for prefix in SKIP_PATH_PREFIXES):
            continue
        path = ROOT / rel
        if not path.exists() or not path.is_file():
            continue
        if path.suffix.lower() in BINARY_EXTENSIONS:
            continue
        result.append(path)
    return result


def _is_allowed_assignment(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in ALLOWED_VALUES:
        return True
    return any(marker in normalized for marker in ALLOWED_VALUE_MARKERS)


def scan() -> list[str]:
    findings: list[str] = []
    for path in _git_tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for line_number, line in enumerate(text.splitlines(), start=1):
            for name, pattern in PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue

                if name == "generic_assignment":
                    value = match.group(2)
                    if _is_allowed_assignment(value):
                        continue

                rel = path.relative_to(ROOT)
                findings.append(f"{rel}:{line_number}: {name}")
    return findings


def main() -> int:
    findings = scan()
    if not findings:
        print("secret scan passed")
        return 0

    print("secret scan failed: potential secrets detected")
    for item in findings:
        print(f"- {item}")
    print("Use environment variables or local .env files, never commit live credentials.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
