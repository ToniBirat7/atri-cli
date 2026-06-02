"""
Tests for services/orchestrator/skills_loader.py
"""
import sys
from pathlib import Path

import pytest

_ORCH_DIR = Path(__file__).resolve().parent.parent
if str(_ORCH_DIR) not in sys.path:
    sys.path.insert(0, str(_ORCH_DIR))

from skills_loader import discover_skills, get_skill_body


SKILL_MD_CONTENT = """\
---
name: test-skill
description: A test skill for unit tests
tools: [read_text_file, bash_exec]
---
This is the full body of the test skill.
It contains detailed instructions.
"""


@pytest.fixture
def skill_dir(tmp_path) -> Path:
    """Create a temporary skills directory with one SKILL.md inside."""
    skills_root = tmp_path / "skills"
    skill_folder = skills_root / "test-skill"
    skill_folder.mkdir(parents=True)
    (skill_folder / "SKILL.md").write_text(SKILL_MD_CONTENT, encoding="utf-8")
    return skills_root


# ── discover_skills ─────────────────────────────────────────────────────────────

def test_discover_skills_finds_skill(skill_dir):
    skills = discover_skills(extra_dirs=[skill_dir])
    assert "test-skill" in skills


def test_discovered_skill_has_correct_fields(skill_dir):
    skills = discover_skills(extra_dirs=[skill_dir])
    skill = skills["test-skill"]
    assert skill.name == "test-skill"
    assert "unit tests" in skill.description
    assert "read_text_file" in skill.tools
    assert "bash_exec" in skill.tools


def test_discover_skills_empty_dir(tmp_path):
    empty_dir = tmp_path / "no-skills"
    empty_dir.mkdir()
    skills = discover_skills(extra_dirs=[empty_dir])
    assert len(skills) == 0


def test_discover_skills_malformed_skill_md(tmp_path):
    """A SKILL.md without frontmatter should be silently skipped."""
    skills_root = tmp_path / "skills"
    bad_folder = skills_root / "bad-skill"
    bad_folder.mkdir(parents=True)
    (bad_folder / "SKILL.md").write_text("No frontmatter here at all.", encoding="utf-8")
    skills = discover_skills(extra_dirs=[skills_root])
    assert "bad-skill" not in skills


# ── get_skill_body ──────────────────────────────────────────────────────────────

def test_get_skill_body_returns_content(skill_dir):
    skills = discover_skills(extra_dirs=[skill_dir])
    body = get_skill_body("test-skill", skills)
    assert body is not None
    assert "full body of the test skill" in body


def test_get_skill_body_unknown_name_returns_none(skill_dir):
    skills = discover_skills(extra_dirs=[skill_dir])
    assert get_skill_body("nonexistent-skill", skills) is None


def test_get_skill_body_empty_skills_dict():
    assert get_skill_body("any-skill", {}) is None
