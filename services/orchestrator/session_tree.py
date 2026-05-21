"""
Tree-structured session storage for atri-cli.
Inspired by Pi's append-only session architecture.

Each turn is a node with UUID + parent_id pointer.
Sessions stored as append-only JSONL: .atri/sessions/<session_id>.jsonl
"""
from __future__ import annotations
import json
import logging
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

__all__ = [
    "SessionEntry",
    "SessionTree",
    "new_entry",
    "SESSIONS_DIR",
]

logger = logging.getLogger(__name__)


SESSIONS_DIR = Path.home() / ".atri" / "sessions"


@dataclass
class SessionEntry:
    id: str                    # UUID of this entry/turn
    parent_id: Optional[str]  # parent entry UUID (None for root)
    session_id: str            # conversation/session UUID
    role: str                  # "user" | "assistant" | "tool" | "system" | "event"
    content: Any               # message content or event payload
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict = field(default_factory=dict)


class SessionTree:
    """
    In-memory index of a session's entries.
    Backed by an append-only JSONL file for persistence.
    """

    def __init__(self, session_id: str, sessions_dir: Path = SESSIONS_DIR):
        self.session_id = session_id
        self.sessions_dir = sessions_dir
        self._entries: dict[str, SessionEntry] = {}  # id -> entry
        self._children: dict[str, list[str]] = {}    # parent_id -> [child_ids]
        self._path: Path = sessions_dir / f"{session_id}.jsonl"
        self._load()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load existing entries from JSONL file."""
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    entry = SessionEntry(**data)
                    self._index(entry)
                except Exception as e:
                    logger.warning("session_tree _load failed to parse line: %s", e, exc_info=True)
                    continue

    def _index(self, entry: SessionEntry) -> None:
        self._entries[entry.id] = entry
        parent = entry.parent_id or "__root__"
        self._children.setdefault(parent, []).append(entry.id)

    def append(self, entry: SessionEntry) -> None:  # C.7
        """Append a new entry to the JSONL log and index it."""
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        self._index(entry)

    # ── Query ──────────────────────────────────────────────────────────────────

    def get(self, entry_id: str) -> Optional[SessionEntry]:  # C.7
        return self._entries.get(entry_id)

    def root_ids(self) -> list[str]:  # C.7
        return self._children.get("__root__", [])

    def children_of(self, entry_id: str) -> list[str]:
        return self._children.get(entry_id, [])

    def leaf_ids(self) -> list[str]:
        """All entries with no children."""
        return [eid for eid in self._entries if not self._children.get(eid)]

    def path_to_leaf(self, leaf_id: str) -> list[SessionEntry]:
        """Return ordered list from root to given leaf."""
        chain: list[str] = []
        current: Optional[str] = leaf_id
        visited: set[str] = set()
        while current and current not in visited:
            visited.add(current)
            chain.append(current)
            entry = self._entries.get(current)
            current = entry.parent_id if entry else None
        return [self._entries[eid] for eid in reversed(chain) if eid in self._entries]

    def to_messages(self, leaf_id: Optional[str] = None) -> list[dict]:
        """
        Reconstruct OpenAI-format messages from root to leaf.
        If leaf_id is None, picks the most recent leaf.
        """
        if leaf_id is None:
            leaves = self.leaf_ids()
            if not leaves:
                return []
            # Pick most recent leaf by timestamp
            leaf_id = max(
                leaves,
                key=lambda lid: self._entries[lid].timestamp if lid in self._entries else "",
            )
        chain = self.path_to_leaf(leaf_id)
        messages = []
        for entry in chain:
            if entry.role in ("user", "assistant", "system", "tool"):
                messages.append({"role": entry.role, "content": entry.content})
        return messages

    def render_tree(self, indent: int = 0, entry_id: Optional[str] = None) -> str:
        """Return ASCII tree string for /tree command."""
        lines: list[str] = []
        if entry_id is None:
            roots = self.root_ids()
            for rid in roots:
                lines.append(self._render_node(rid, indent=0))
        else:
            lines.append(self._render_node(entry_id, indent=indent))
        return "\n".join(lines)

    def _render_node(self, entry_id: str, indent: int) -> str:
        entry = self._entries.get(entry_id)
        if not entry:
            return ""
        prefix = "  " * indent + ("├─ " if indent > 0 else "")
        content_preview = str(entry.content)[:60].replace("\n", " ")
        node_line = f"{prefix}[{entry.id[:8]}] {entry.role}: {content_preview}"
        children = self._children.get(entry_id, [])
        child_lines = [self._render_node(cid, indent + 1) for cid in children]
        return "\n".join([node_line] + child_lines)

    # ── Fork ───────────────────────────────────────────────────────────────────

    def fork(self, from_entry_id: str) -> str:  # C.7
        """
        Create a fork point at the given entry. Returns a new session_id.
        The new session's JSONL will be initialized with all entries up to from_entry_id.
        """
        new_session_id = str(uuid.uuid4())
        new_tree = SessionTree(new_session_id, self.sessions_dir)
        chain = self.path_to_leaf(from_entry_id)
        for entry in chain:
            forked = SessionEntry(
                id=entry.id,
                parent_id=entry.parent_id,
                session_id=new_session_id,
                role=entry.role,
                content=entry.content,
                timestamp=entry.timestamp,
                metadata={**entry.metadata, "forked_from": self.session_id},
            )
            new_tree.append(forked)
        return new_session_id


def new_entry(
    session_id: str,
    role: str,
    content: Any,
    parent_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> SessionEntry:
    """Convenience constructor for a new SessionEntry."""
    return SessionEntry(
        id=str(uuid.uuid4()),
        parent_id=parent_id,
        session_id=session_id,
        role=role,
        content=content,
        metadata=metadata or {},
    )
