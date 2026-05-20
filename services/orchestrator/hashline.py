"""Hash-anchored line editing — reduces edit output tokens by ~61%.

Every line is annotated as 'LINENUM#HASH|TEXT'. The LLM uses an edit DSL
instead of sending full file content. All hashes are validated atomically
before any file mutation — either every edit applies or none does.
"""
from __future__ import annotations

import hashlib
import re
from typing import NamedTuple


# ─── Public exception ─────────────────────────────────────────────────────────

class HashMismatchError(ValueError):
    """Raised when a hashline anchor does not match the actual file content."""


# ─── Encoding ─────────────────────────────────────────────────────────────────

def encode_file(content: str) -> str:
    """Return content with line-hash anchors.

    Format per line: ``LINENUM#HASH|TEXT\\n``

    Example::

        1#a1b2|first line
        2#c3d4|second line

    The hash is the first 4 hex characters of the MD5 of the stripped line text.
    Trailing newlines are stripped from each line before hashing so that
    ``encode_file`` is deterministic regardless of line-ending style.
    """
    lines = content.splitlines(keepends=True)
    out: list[str] = []
    for i, line in enumerate(lines, 1):
        stripped = line.rstrip("\n").rstrip("\r")
        h = hashlib.md5(stripped.encode("utf-8")).hexdigest()[:4]
        out.append(f"{i}#{h}|{stripped}\n")
    return "".join(out)


# ─── DSL types ────────────────────────────────────────────────────────────────

class EditOp(NamedTuple):
    """A single parsed edit operation."""

    op: str       # "replace" | "insert_after" | "insert_before" | "delete"
    anchor: str   # "LINENUM#HASH" or "LINENUM_START#HASH..LINENUM_END#HASH"
    content: str  # new content lines (empty for delete)


# ─── DSL parser ───────────────────────────────────────────────────────────────

_OP_MAP = {
    "=": "replace",
    "+": "insert_after",
    "<": "insert_before",
    "-": "delete",
}

_ANCHOR_RE = re.compile(r"^\d+#[0-9a-f]{4}(\.\.\d+#[0-9a-f]{4})?$")


def parse_edits(edit_dsl: str) -> list[EditOp]:
    """Parse the hashline edit DSL into a list of :class:`EditOp`.

    DSL grammar (one block per edit, blocks separated by ``---``)::

        = START#HASH..END#HASH
        replacement line 1
        replacement line 2
        ---
        + ANCHOR#HASH
        inserted line
        ---
        < ANCHOR#HASH
        inserted before line
        ---
        - START#HASH..END#HASH

    Opcode meanings:

    * ``=``  replace the range with the following lines
    * ``+``  insert the following lines *after* the anchor line
    * ``<``  insert the following lines *before* the anchor line
    * ``-``  delete the range (no following content expected)
    """
    ops: list[EditOp] = []
    # Split on --- separators; each segment is one edit block
    segments = re.split(r"^---\s*$", edit_dsl, flags=re.MULTILINE)
    for segment in segments:
        lines = segment.strip().splitlines()
        if not lines:
            continue
        header = lines[0].strip()
        if not header or header[0] not in _OP_MAP:
            raise ValueError(f"Invalid DSL header: {header!r}")
        op_char = header[0]
        anchor = header[1:].strip()
        if not _ANCHOR_RE.match(anchor):
            raise ValueError(f"Invalid anchor format: {anchor!r}. Expected LINENUM#HASH or LINENUM#HASH..LINENUM#HASH")
        content_lines = lines[1:]
        # Strip one leading blank line if present (after the header)
        if content_lines and content_lines[0] == "":
            content_lines = content_lines[1:]
        content = "\n".join(content_lines)
        ops.append(EditOp(op=_OP_MAP[op_char], anchor=anchor, content=content))
    return ops


# ─── Anchor resolution helpers ────────────────────────────────────────────────

def _line_hash(text: str) -> str:
    stripped = text.rstrip("\n").rstrip("\r")
    return hashlib.md5(stripped.encode("utf-8")).hexdigest()[:4]


def _parse_single_anchor(anchor_str: str) -> tuple[int, str]:
    """Return (1-based line number, expected hash) from 'LINENUM#HASH'."""
    num_part, hash_part = anchor_str.split("#", 1)
    return int(num_part), hash_part


def _parse_range_anchor(anchor: str) -> tuple[tuple[int, str], tuple[int, str] | None]:
    """Return (start_anchor, end_anchor | None) from an anchor string."""
    if ".." in anchor:
        start_str, end_str = anchor.split("..", 1)
        return _parse_single_anchor(start_str), _parse_single_anchor(end_str)
    return _parse_single_anchor(anchor), None


# ─── Atomic application ───────────────────────────────────────────────────────

def apply_hashline_edits(original_content: str, edit_dsl: str) -> str:
    """Apply hashline edits atomically.

    Validates ALL anchors against *original_content* before mutating anything.
    If any hash does not match, raises :class:`HashMismatchError` and the
    original file is left untouched.

    Parameters
    ----------
    original_content:
        The current file content as a plain string.
    edit_dsl:
        The edit DSL string produced by the LLM.

    Returns
    -------
    str
        The new file content after applying all edits.

    Raises
    ------
    HashMismatchError
        If any anchor hash does not match the corresponding line.
    ValueError
        If the DSL is malformed.
    """
    ops = parse_edits(edit_dsl)
    if not ops:
        return original_content

    # Work with a list of lines (no trailing newline on last line is fine)
    lines: list[str] = original_content.splitlines(keepends=True)
    # Normalise: ensure every line ends with \n for uniform indexing
    for idx, line in enumerate(lines):
        if not line.endswith("\n"):
            lines[idx] = line + "\n"

    # ── Phase 1: validate ALL anchors ────────────────────────────────────────
    for op in ops:
        start_anchor, end_anchor = _parse_range_anchor(op.anchor)
        start_lineno, start_hash = start_anchor

        if start_lineno < 1 or start_lineno > len(lines):
            raise HashMismatchError(
                f"Line {start_lineno} is out of range (file has {len(lines)} lines)"
            )
        actual_hash = _line_hash(lines[start_lineno - 1])
        if actual_hash != start_hash:
            line_text = lines[start_lineno - 1].rstrip("\n")
            raise HashMismatchError(
                f"Hash mismatch at line {start_lineno}: "
                f"expected #{start_hash}, got #{actual_hash} "
                f"(line content: {line_text!r})"
            )

        if end_anchor is not None:
            end_lineno, end_hash = end_anchor
            if end_lineno < start_lineno or end_lineno > len(lines):
                raise HashMismatchError(
                    f"End line {end_lineno} is out of range or before start {start_lineno}"
                )
            actual_end_hash = _line_hash(lines[end_lineno - 1])
            if actual_end_hash != end_hash:
                line_text = lines[end_lineno - 1].rstrip("\n")
                raise HashMismatchError(
                    f"Hash mismatch at end line {end_lineno}: "
                    f"expected #{end_hash}, got #{actual_end_hash} "
                    f"(line content: {line_text!r})"
                )

    # ── Phase 2: apply edits in reverse line order (so indices stay valid) ──
    # Sort ops by start line descending so that later edits don't shift
    # earlier line indices.
    def _start_line(op: EditOp) -> int:
        start_anchor, _ = _parse_range_anchor(op.anchor)
        return start_anchor[0]

    sorted_ops = sorted(ops, key=_start_line, reverse=True)

    for op in sorted_ops:
        start_anchor, end_anchor = _parse_range_anchor(op.anchor)
        start_lineno, _ = start_anchor
        end_lineno = end_anchor[0] if end_anchor else start_lineno

        # Build replacement block (ensure each line ends with \n)
        new_lines: list[str] = []
        if op.content:
            for ln in op.content.splitlines():
                new_lines.append(ln + "\n")

        # 0-based slice indices
        s = start_lineno - 1
        e = end_lineno  # exclusive end

        if op.op == "replace":
            lines[s:e] = new_lines
        elif op.op == "delete":
            lines[s:e] = []
        elif op.op == "insert_after":
            # Insert after the anchor line (which is NOT deleted)
            lines[s + 1:s + 1] = new_lines
        elif op.op == "insert_before":
            lines[s:s] = new_lines
        else:
            raise ValueError(f"Unknown op: {op.op!r}")

    result = "".join(lines)
    # Strip the normalisation newline we may have added to the final line
    if not original_content.endswith("\n") and result.endswith("\n"):
        result = result[:-1]
    return result
