"""
Tests for services/orchestrator/session_tree.py
"""
import json
import sys
import uuid
from pathlib import Path

import pytest

_ORCH_DIR = Path(__file__).resolve().parent.parent
if str(_ORCH_DIR) not in sys.path:
    sys.path.insert(0, str(_ORCH_DIR))

from session_tree import SessionTree, SessionEntry, new_entry


@pytest.fixture
def tmp_session(tmp_path) -> SessionTree:
    """Return a fresh SessionTree backed by a temp directory."""
    session_id = str(uuid.uuid4())
    return SessionTree(session_id, sessions_dir=tmp_path)


# ── append / get round-trip ─────────────────────────────────────────────────────

def test_append_and_get(tmp_session):
    entry = new_entry(
        session_id=tmp_session.session_id,
        role="user",
        content="Hello world",
    )
    tmp_session.append(entry)
    fetched = tmp_session.get(entry.id)
    assert fetched is not None
    assert fetched.content == "Hello world"
    assert fetched.role == "user"


def test_get_missing_entry_returns_none(tmp_session):
    assert tmp_session.get("nonexistent-id") is None


# ── fork ────────────────────────────────────────────────────────────────────────

def test_fork_creates_child_session(tmp_session):
    root = new_entry(tmp_session.session_id, "user", "turn 1")
    tmp_session.append(root)
    child_id = new_entry(tmp_session.session_id, "assistant", "response 1", parent_id=root.id)
    tmp_session.append(child_id)

    new_session_id = tmp_session.fork(child_id.id)
    assert new_session_id != tmp_session.session_id
    assert isinstance(new_session_id, str)


def test_fork_new_tree_has_entries(tmp_session):
    root = new_entry(tmp_session.session_id, "user", "original", parent_id=None)
    tmp_session.append(root)
    new_sid = tmp_session.fork(root.id)

    forked_tree = SessionTree(new_sid, sessions_dir=tmp_session.sessions_dir)
    assert len(forked_tree._entries) >= 1


# ── render_tree ─────────────────────────────────────────────────────────────────

def test_render_tree_non_empty(tmp_session):
    e = new_entry(tmp_session.session_id, "user", "some content")
    tmp_session.append(e)
    rendered = tmp_session.render_tree()
    assert len(rendered) > 0
    assert e.id[:8] in rendered


def test_render_tree_empty_session_is_empty_string(tmp_session):
    rendered = tmp_session.render_tree()
    assert rendered == ""


# ── JSONL serialization round-trip ──────────────────────────────────────────────

def test_jsonl_roundtrip(tmp_path):
    session_id = str(uuid.uuid4())
    tree = SessionTree(session_id, sessions_dir=tmp_path)

    entry = new_entry(session_id, "assistant", {"key": "value"})
    tree.append(entry)

    # Reload from disk
    reloaded = SessionTree(session_id, sessions_dir=tmp_path)
    fetched = reloaded.get(entry.id)
    assert fetched is not None
    assert fetched.role == "assistant"
    assert fetched.content == {"key": "value"}


def test_jsonl_file_exists_after_append(tmp_path):
    session_id = str(uuid.uuid4())
    tree = SessionTree(session_id, sessions_dir=tmp_path)
    tree.append(new_entry(session_id, "user", "hello"))

    jsonl_file = tmp_path / f"{session_id}.jsonl"
    assert jsonl_file.exists()
    lines = [l for l in jsonl_file.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["role"] == "user"
