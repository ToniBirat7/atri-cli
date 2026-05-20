"""
Differential TUI renderer for atri-cli.
Inspired by Pi's pi-tui rendering engine.

Three strategies:
1. FIRST: Full draw on initial render
2. RESIZE: Full redraw on terminal resize
3. DIFF: Only changed lines updated via ANSI cursor positioning
"""
from __future__ import annotations
import sys
import shutil
from enum import Enum, auto


class RenderStrategy(Enum):
    FIRST = auto()
    RESIZE = auto()
    DIFF = auto()


class DifferentialRenderer:
    """
    Tracks previous frame and renders only changed lines.
    Eliminates flicker during token streaming.
    """

    def __init__(self, stream=None):
        self._stream = stream or sys.stdout
        self._prev_lines: list[str] = []
        self._term_cols, self._term_rows = shutil.get_terminal_size((80, 24))
        self._first_render = True

    def get_term_size(self) -> tuple[int, int]:
        return shutil.get_terminal_size((80, 24))

    def render(self, lines: list[str]) -> None:
        """Render a frame. Automatically chooses strategy."""
        cols, rows = self.get_term_size()
        size_changed = (cols != self._term_cols or rows != self._term_rows)
        self._term_cols, self._term_rows = cols, rows

        if self._first_render:
            strategy = RenderStrategy.FIRST
            self._first_render = False
        elif size_changed:
            strategy = RenderStrategy.RESIZE
        else:
            strategy = RenderStrategy.DIFF

        if strategy in (RenderStrategy.FIRST, RenderStrategy.RESIZE):
            self._full_draw(lines)
        else:
            self._diff_draw(lines)

        self._prev_lines = list(lines)

    def _full_draw(self, lines: list[str]) -> None:
        self._stream.write("\033[2J\033[H")  # clear screen, cursor home
        self._stream.write("\n".join(lines))
        self._stream.flush()

    def _diff_draw(self, lines: list[str]) -> None:
        """Update only changed lines using ANSI cursor positioning."""
        out_parts: list[str] = []
        max_len = max(len(lines), len(self._prev_lines))
        for i in range(max_len):
            new_line = lines[i] if i < len(lines) else ""
            old_line = self._prev_lines[i] if i < len(self._prev_lines) else None
            if new_line != old_line:
                # Move cursor to line i+1, column 1; clear line; write new content
                out_parts.append(f"\033[{i+1};1H\033[2K{new_line}")
        if out_parts:
            self._stream.write("".join(out_parts))
            self._stream.flush()

    def clear(self) -> None:
        self._stream.write("\033[2J\033[H")
        self._stream.flush()
        self._prev_lines = []
        self._first_render = True
