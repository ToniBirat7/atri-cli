"""
Context window auto-compaction for atri-cli.
Inspired by Pi's compaction pipeline + Gemini's chat compression service.

When token usage approaches ctx_size (80% threshold), summarizes oldest turns
into a single system message and re-attaches last 5 file reads.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

COMPACTION_THRESHOLD = 0.80   # compact when 80% of ctx used
MAX_FILE_REATTACH = 5         # re-attach up to 5 recently-read files post-compact


def should_compact(prompt_tokens: int, ctx_size: int) -> bool:
    """Return True if context usage exceeds the compaction threshold."""
    return ctx_size > 0 and (prompt_tokens / ctx_size) >= COMPACTION_THRESHOLD


def extract_recent_file_reads(messages: list[dict]) -> list[str]:
    """
    Scan tool result messages for file read content. Returns up to MAX_FILE_REATTACH
    unique file paths (most recent first) to re-attach after compaction.
    """
    seen_paths: list[str] = []
    for msg in reversed(messages):
        if msg.get("role") != "tool":
            continue
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                c.get("text", "") for c in content if isinstance(c, dict)
            )
        # Heuristic: tool results from read_text_file / read_file contain a path marker
        path_match = re.search(
            r"(?:file|path)[\"']?\s*[:=]\s*[\"']?([^\s\"',}]+)",
            str(content),
            re.IGNORECASE,
        )
        if path_match:
            p = path_match.group(1).strip()
            if p not in seen_paths:
                seen_paths.append(p)
        if len(seen_paths) >= MAX_FILE_REATTACH:
            break
    return seen_paths


async def compact_messages(
    messages: list[dict],
    llm_adapter: Any,
    ctx_size: int,
    event_callback: Any = None,
) -> list[dict]:
    """
    Summarize oldest turns and return a compacted message list.
    Keeps: system prompt, last 10 messages, compaction summary.
    """
    if len(messages) <= 4:
        return messages  # nothing worth compacting

    system_msg = messages[0] if messages[0].get("role") == "system" else None

    keep_recent = 10
    if system_msg:
        to_summarize = messages[1:-keep_recent] if len(messages) > keep_recent + 1 else []
        recent = messages[-keep_recent:]
    else:
        to_summarize = messages[:-keep_recent] if len(messages) > keep_recent else []
        recent = messages[-keep_recent:]

    if not to_summarize:
        return messages

    # Build summarization prompt
    history_text = "\n".join(
        f"[{m.get('role', '?').upper()}]: {_msg_text(m)[:500]}"
        for m in to_summarize
    )
    summary_prompt = [
        {
            "role": "system",
            "content": (
                "You are a concise summarizer. Summarize the following conversation "
                "history into a brief paragraph preserving key facts, files read, and "
                "decisions made. Be specific about file paths and code changes."
            ),
        },
        {
            "role": "user",
            "content": f"Summarize this conversation history:\n\n{history_text}",
        },
    ]

    try:
        summary_completion = await llm_adapter.chat_completion(
            messages=summary_prompt,
            tools=None,
            temperature=0.3,
            enable_thinking=False,
        )
        summary_text = (
            summary_completion.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
    except Exception as exc:
        logger.warning("Compaction LLM call failed: %s — skipping compaction", exc)
        return messages

    if not summary_text:
        return messages

    compaction_note = (
        f"[Context compacted — {len(to_summarize)} messages summarized]\n\n{summary_text}"
    )

    compacted: list[dict] = []
    if system_msg:
        compacted.append(system_msg)
    compacted.append({"role": "user", "content": compaction_note})
    compacted.append(
        {
            "role": "assistant",
            "content": (
                "Understood. I have the context from the summarized history and will continue."
            ),
        }
    )
    compacted.extend(recent)

    logger.info(
        "Context compacted: %d messages → %d (summary: %d chars)",
        len(messages),
        len(compacted),
        len(summary_text),
    )

    if event_callback is not None:
        try:
            maybe = event_callback(
                {
                    "type": "context_compacted",
                    "original_messages": len(messages),
                    "compacted_messages": len(compacted),
                    "summary_length": len(summary_text),
                }
            )
            if asyncio.iscoroutine(maybe):
                await maybe
        except Exception:
            pass

    return compacted


def _msg_text(msg: dict) -> str:
    """Extract plain text from a message dict."""
    content = msg.get("content", "")
    if isinstance(content, list):
        return " ".join(
            c.get("text", "") if isinstance(c, dict) else str(c) for c in content
        )
    return str(content or "")
