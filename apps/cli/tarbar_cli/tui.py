from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from typing import Any, Optional

TIMELINE_VERBOSITY_LEVELS = ("minimal", "normal", "debug")


@dataclass
class TurnStatus:
    turn_number: int
    elapsed_seconds: float
    input_tokens: int
    output_tokens: int
    tool_calls: int
    phase: str


class TUIRenderer:
    def __init__(self, timeline_verbosity: str = "normal") -> None:
        self.timeline_verbosity = timeline_verbosity
        self._status_active = False
        self._status_last_len = 0

    @staticmethod
    def supports_color() -> bool:
        if os.getenv("NO_COLOR"):
            return False
        if not sys.stdout.isatty():
            return False
        term = os.getenv("TERM", "")
        return bool(term and term.lower() != "dumb")

    @staticmethod
    def is_tty() -> bool:
        return sys.stdout.isatty()

    def style(self, text: str, *, color: Optional[str] = None, bold: bool = False, dim: bool = False) -> str:
        ansi = {
            "reset": "\033[0m",
            "bold": "\033[1m",
            "dim": "\033[2m",
            "red": "\033[31m",
            "yellow": "\033[33m",
            "green": "\033[32m",
            "cyan": "\033[36m",
        }
        if not self.supports_color():
            return text

        parts: list[str] = []
        if bold:
            parts.append(ansi["bold"])
        if dim:
            parts.append(ansi["dim"])
        if color and color in ansi:
            parts.append(ansi[color])
        if not parts:
            return text
        return "".join(parts) + text + ansi["reset"]

    def print_info(self, message: str) -> None:
        print(self.style(f"[info] {message}", color="cyan"))

    def print_success(self, message: str) -> None:
        print(self.style(f"[ok] {message}", color="green"))

    def print_warning(self, message: str) -> None:
        print(self.style(f"[warn] {message}", color="yellow"))

    def print_error(self, message: str) -> None:
        print(self.style(f"[error] {message}", color="red", bold=True), file=sys.stderr)

    def set_timeline_verbosity(self, level: str) -> None:
        if level not in TIMELINE_VERBOSITY_LEVELS:
            valid = ", ".join(TIMELINE_VERBOSITY_LEVELS)
            raise ValueError(f"Invalid timeline verbosity: {level}. Valid levels: {valid}")
        self.timeline_verbosity = level

    def status_set(self, status: TurnStatus) -> None:
        if not self.is_tty():
            return
        line_text = (
            f"status: turn {status.turn_number} | {status.phase} | "
            f"elapsed {status.elapsed_seconds:.1f}s | in {status.input_tokens} tok | "
            f"out {status.output_tokens} tok | tools {status.tool_calls}"
        )
        line = self.style(line_text, color="cyan", dim=True)
        padded = line
        plain_len = len(line_text)
        if self._status_last_len > plain_len:
            padded += " " * (self._status_last_len - plain_len)
        print("\r" + padded, end="", flush=True)
        self._status_active = True
        self._status_last_len = plain_len

    def status_clear(self) -> None:
        if not self.is_tty() or not self._status_active:
            return
        print("\r" + (" " * max(0, self._status_last_len + 2)) + "\r", end="", flush=True)
        self._status_active = False
        self._status_last_len = 0

    def print_status_summary(self, status: TurnStatus) -> None:
        line = (
            f"status: turn {status.turn_number} | {status.phase} | "
            f"elapsed {status.elapsed_seconds:.1f}s | in {status.input_tokens} tok | "
            f"out {status.output_tokens} tok | tools {status.tool_calls}"
        )
        print(self.style(line, color="cyan", dim=True))

    def print_turn_card(self, turn_number: int, mode: str) -> None:
        header = f" turn {turn_number} | mode={mode} "
        border = "-" * max(8, len(header))
        print(self.style(border, dim=True))
        print(self.style(header, dim=True))
        print(self.style(border, dim=True))

    def print_welcome_dashboard(self, mode: str, api_url: str) -> None:
        width = shutil.get_terminal_size((100, 24)).columns
        width = max(72, min(width, 120))
        left_width = max(28, int(width * 0.45))
        right_width = width - left_width - 3

        left_lines = [
            self.style("Welcome to Tarbar CLI", color="cyan", bold=True),
            "",
            "Local-first coding agent runtime",
            f"Permission mode: {mode}",
            f"API endpoint: {api_url}",
        ]
        right_lines = [
            self.style("Tips", color="yellow", bold=True),
            "",
            "Type /help for commands",
            "Type /mode to inspect policy mode",
            "Type /timeline minimal|normal|debug",
            "Type /exit to quit",
        ]

        def _fit(line: str, max_width: int) -> str:
            if len(line) <= max_width:
                return line
            if max_width <= 3:
                return line[:max_width]
            return line[: max_width - 3] + "..."

        total_rows = max(len(left_lines), len(right_lines))
        print(self.style("=" * width, dim=True))
        for idx in range(total_rows):
            left_raw = left_lines[idx] if idx < len(left_lines) else ""
            right_raw = right_lines[idx] if idx < len(right_lines) else ""
            left = _fit(left_raw, left_width).ljust(left_width)
            right = _fit(right_raw, right_width).ljust(right_width)
            print(f"{left} {self.style('|', dim=True)} {right}")
        print(self.style("=" * width, dim=True))

    def should_render_timeline(self, event_type: str) -> bool:
        if self.timeline_verbosity == "debug":
            return True
        if self.timeline_verbosity == "minimal":
            return event_type in {"tool_call_start", "tool_call_result", "agent_complete"}
        return event_type in {
            "turn_start",
            "llm_response",
            "tool_call_start",
            "tool_call_result",
            "turn_complete",
            "agent_complete",
        }

    def render_timeline_event(self, event: dict[str, Any], output_format: str) -> None:
        if output_format != "text":
            return
        event_type = str(event.get("type") or "").strip()
        if not event_type or not self.should_render_timeline(event_type):
            return

        if self.timeline_verbosity == "debug":
            self.print_info(f"event {event_type}: {json.dumps(event, sort_keys=True, ensure_ascii=False)}")
            return

        if event_type == "turn_start":
            self.print_info(f"turn {event.get('turn')} started")
        elif event_type == "llm_response":
            self.print_info("model responded")
        elif event_type == "tool_call_start":
            self.print_info(f"tool call started: {event.get('tool_name', 'tool')}")
        elif event_type == "tool_call_result":
            tool_name = event.get("tool_name", "tool")
            status = event.get("status", "ok")
            if status == "ok":
                self.print_success(f"tool call finished: {tool_name}")
            else:
                self.print_warning(f"tool call failed: {tool_name}")
        elif event_type == "turn_complete":
            self.print_info(f"turn {event.get('turn')} complete")
        elif event_type == "agent_complete":
            self.print_success("agent complete")
