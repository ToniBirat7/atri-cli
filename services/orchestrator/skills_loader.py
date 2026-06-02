"""
Skills system for atri-cli.
Inspired by Pi's SKILL.md progressive disclosure model.

Skills live in:
  - ~/.atri/skills/<skill-name>/SKILL.md   (user-global)
  - .atri/skills/<skill-name>/SKILL.md     (project-local, takes precedence)

Each SKILL.md has YAML frontmatter + markdown body:
  ---
  name: my-skill
  description: One-line description shown in prompt and /skills listing
  tools: [read_text_file, bash_exec]
  ---
  Full skill instructions here. Only loaded when the skill is invoked.

At prompt-build time: only the description is injected (keeps token usage flat).
Full body is loaded only when the agent calls invoke_skill(name).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


@dataclass
class Skill:
    name: str
    description: str
    tools: list[str] = field(default_factory=list)
    body: str = ""
    source_path: str = ""
    source: str = "user"  # "user" | "auto"


def _parse_skill_md(path: Path) -> Optional[Skill]:
    """Parse a SKILL.md file. Returns None if malformed."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None

    # Split frontmatter (---\n...\n---\n)
    if not content.startswith("---"):
        return None

    parts = content.split("---", 2)
    if len(parts) < 3:
        return None

    fm_text = parts[1].strip()
    body = parts[2].strip()

    # Parse frontmatter
    fm: dict[str, Any] = {}
    if _YAML_AVAILABLE:
        try:
            fm = yaml.safe_load(fm_text) or {}
        except Exception:
            return None
    else:
        # Minimal key: value parser
        for line in fm_text.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip()

    name = fm.get("name", path.parent.name)
    description = fm.get("description", "")
    tools_raw = fm.get("tools", [])
    if isinstance(tools_raw, str):
        tools_raw = [t.strip() for t in tools_raw.split(",")]

    return Skill(
        name=str(name),
        description=str(description),
        tools=list(tools_raw),
        body=body,
        source_path=str(path),
        source=str(fm.get("source", "user")),
    )


def discover_skills(extra_dirs: list[Path] | None = None) -> dict[str, Skill]:
    """
    Discover all skills. Project-local skills override user-global skills.
    Returns dict of name -> Skill.
    """
    search_dirs: list[Path] = [
        Path.home() / ".atri" / "skills",
    ]
    # Project-local: look for .atri/skills relative to cwd
    project_skills = Path.cwd() / ".atri" / "skills"
    if project_skills.exists():
        search_dirs.append(project_skills)

    if extra_dirs:
        search_dirs.extend(extra_dirs)

    skills: dict[str, Skill] = {}
    for skills_dir in search_dirs:
        if not skills_dir.exists():
            continue
        for skill_dir in sorted(skills_dir.iterdir()):
            skill_md = skill_dir / "SKILL.md" if skill_dir.is_dir() else (
                skill_dir if skill_dir.name == "SKILL.md" else None
            )
            if skill_md is None or not skill_md.exists():
                continue
            skill = _parse_skill_md(skill_md)
            if skill:
                skills[skill.name] = skill  # later dirs override earlier

    return skills


def build_skills_prompt_snippet(skills: dict[str, Skill]) -> str:
    """Build the short snippet injected into system prompt (descriptions only)."""
    if not skills:
        return ""

    lines = ["## Available Skills\n"]
    for skill in skills.values():
        if skill.source == "auto":
            continue  # don't surface auto-extracted skills without review
        lines.append(f"- **{skill.name}**: {skill.description}")

    if len(lines) == 1:
        return ""

    lines.append("\nCall `invoke_skill` with the skill name to use a skill's full instructions.")
    return "\n".join(lines)


def get_skill_body(name: str, skills: dict[str, Skill]) -> Optional[str]:
    """Return the full body of a skill (for invoke_skill tool)."""
    skill = skills.get(name)
    return skill.body if skill else None
