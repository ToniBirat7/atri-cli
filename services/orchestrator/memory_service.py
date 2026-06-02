"""
Auto memory / session mining for atri-cli.
Inspired by Gemini's auto memory extraction.

After sessions with 10+ turns end, extracts reusable patterns into
~/.atri/skills/ as auto-generated skills (source: auto).
These are never auto-applied — they appear in /skills for user review.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# C.4: Module-level defaults — can be overridden at runtime via config parameter
SKILLS_DIR = Path.home() / ".atri" / "skills"
MIN_TURNS_FOR_MINING = 10


async def maybe_mine_session(
    messages: list[dict],
    llm_adapter: Any,
    session_id: str = "",
    config: Any = None,
) -> list[str]:
    """
    If the session has enough turns, mine it for reusable patterns.
    Returns list of skill names created (may be empty).
    Non-blocking: catches all exceptions internally.
    """
    # C.4: Use config values when provided, fall back to module-level defaults
    _min_turns = MIN_TURNS_FOR_MINING
    _skills_dir = SKILLS_DIR
    if config is not None:
        _mem_cfg = getattr(config, "memory", None)
        if _mem_cfg is not None:
            _min_turns = getattr(_mem_cfg, "min_turns_for_mining", _min_turns)
            _raw_dir = getattr(_mem_cfg, "skills_dir", None)
            if _raw_dir:
                _skills_dir = Path(_raw_dir).expanduser()

    # Count meaningful turns (user + assistant pairs)
    turns = sum(1 for m in messages if m.get("role") == "user")
    if turns < _min_turns:
        return []

    logger.info("Memory mining: session has %d turns, extracting patterns...", turns)

    try:
        return await _extract_skills(messages, llm_adapter, session_id, skills_dir=_skills_dir)
    except Exception as e:
        logger.warning("Memory mining failed: %s", e)
        return []


async def _extract_skills(
    messages: list[dict],
    llm_adapter: Any,
    session_id: str,
    skills_dir: Path | None = None,
) -> list[str]:
    """Use LLM to identify reusable patterns from the session."""
    # Build a compact session summary for the LLM to analyze
    history_lines = []
    for m in messages:
        role = m.get("role", "")
        if role not in ("user", "assistant"):
            continue
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
        text = str(content)[:300]
        history_lines.append(f"[{role.upper()}]: {text}")

    if not history_lines:
        return []

    history_text = "\n".join(history_lines[:60])  # cap at 60 messages for the mining prompt

    mining_prompt = [
        {"role": "system", "content": "You extract reusable workflow patterns from conversation history. Output JSON only."},
        {"role": "user", "content": f"""Analyze this conversation and identify any reusable workflow patterns, recurring tasks, or useful procedures that could be saved as named skills.

Conversation:
{history_text}

Output a JSON array of skills (empty array if none found):
[
  {{
    "name": "kebab-case-name",
    "description": "One sentence description",
    "body": "Step-by-step instructions for this skill"
  }}
]

Rules:
- Only extract genuinely reusable patterns (not one-off tasks)
- Maximum 3 skills per session
- If nothing reusable, return []"""},
    ]

    try:
        completion = await llm_adapter.chat_completion(
            messages=mining_prompt,
            tools=None,
            temperature=0.3,
            enable_thinking=False,
        )
        content = completion.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        logger.warning("Mining LLM call failed: %s", e)
        return []

    # Parse JSON from response
    skills_data = _parse_json_array(content)
    if not skills_data:
        return []

    _active_skills_dir = skills_dir if skills_dir is not None else SKILLS_DIR

    created: list[str] = []
    for item in skills_data[:3]:  # max 3
        name = re.sub(r"[^a-z0-9\-]", "", str(item.get("name", "")).lower().replace(" ", "-"))
        if not name:
            continue
        description = str(item.get("description", ""))
        body = str(item.get("body", ""))

        # Write to <skills_dir>/<name>/SKILL.md
        skill_dir = _active_skills_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_md = skill_dir / "SKILL.md"

        if skill_md.exists():
            continue  # never overwrite existing skills

        fm = (
            f"---\n"
            f"name: {name}\n"
            f"description: {description}\n"
            f"source: auto\n"
            f"extracted_from: {session_id}\n"
            f"extracted_at: {datetime.now(timezone.utc).isoformat()}\n"
            f"---\n\n{body}\n"
        )
        tmp_path = skill_md.with_suffix(".tmp")
        tmp_path.write_text(fm, encoding="utf-8")
        os.rename(tmp_path, skill_md)
        created.append(name)
        logger.info("Memory mining: created skill '%s' at %s", name, skill_md)

    return created


def _parse_json_array(text: str) -> list[dict]:
    """Extract a JSON array from LLM output (may have surrounding text)."""
    # Find the first [ ... ] block
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return []
    try:
        result = json.loads(m.group())
        if isinstance(result, list):
            return result
    except Exception:
        pass
    return []
