"""
Rich-based Terminal UI for Atri Code CLI.

Provides beautiful, Claude Code-quality rendering using the Rich library:
- Markdown rendering with syntax-highlighted code blocks
- Animated spinners during thinking
- Bordered panels for tool calls and results
- Interactive permission prompts
- Live streaming with flicker-free updates
- Status bar with token counts and timing
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Optional

# Rich imports — gracefully degrade if not available
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.spinner import Spinner
    from rich.live import Live
    from rich.syntax import Syntax
    from rich.table import Table
    from rich.text import Text
    from rich.theme import Theme
    from rich.rule import Rule
    from rich.columns import Columns
    from rich.box import ROUNDED, HEAVY, SIMPLE, DOUBLE
    from rich import box

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

TIMELINE_VERBOSITY_LEVELS = ("minimal", "normal", "debug")

# ─── Color theme ───────────────────────────────────────────────────────────

if RICH_AVAILABLE:
    ATRI_THEME = Theme({
        "atri.header": "bold bright_cyan",
        "atri.prompt": "bold bright_cyan",
        "atri.assistant": "bright_white",
        "atri.success": "bold green",
        "atri.warning": "bold yellow",
        "atri.error": "bold red",
        "atri.dim": "dim white",
        "atri.tool": "bold magenta",
        "atri.tool_result": "green",
        "atri.thinking": "dim italic cyan",
        "atri.tokens": "dim bright_blue",
        "atri.mode": "bold bright_yellow",
        "atri.separator": "dim cyan",
        "atri.key": "bold bright_white",
        "atri.value": "bright_white",
    })
else:
    ATRI_THEME = None


@dataclass
class TurnStatus:
    turn_number: int
    elapsed_seconds: float
    input_tokens: int
    output_tokens: int
    tool_calls: int
    phase: str


class RichTUI:
    """Rich-based TUI renderer for Atri Code CLI."""

    def __init__(self, timeline_verbosity: str = "normal") -> None:
        self.timeline_verbosity = timeline_verbosity
        self._compact_mode = False
        self._console = Console(theme=ATRI_THEME) if (RICH_AVAILABLE and ATRI_THEME) else (Console() if RICH_AVAILABLE else None)
        self._live: Optional[Live] = None
        self._stream_buffer = ""

    @property
    def console(self) -> Console:
        if self._console is None:
            raise RuntimeError("Rich is not available")
        return self._console

    def set_timeline_verbosity(self, level: str) -> None:
        if level in TIMELINE_VERBOSITY_LEVELS:
            self.timeline_verbosity = level

    def toggle_compact(self) -> bool:
        self._compact_mode = not self._compact_mode
        return self._compact_mode

    @staticmethod
    def is_available() -> bool:
        return RICH_AVAILABLE

    # ─── Welcome ───────────────────────────────────────────────────────────

    def render_welcome(
        self,
        api_url: str = "http://127.0.0.1:8001",
        permission_mode: str = "default",
        model: str = "Gemma 4 E2B",
        reasoning: bool = True,
    ) -> None:
        """Render the startup welcome banner."""
        if not RICH_AVAILABLE:
            print("\n  Atri Code — Local AI coding agent")
            print(f"  Model: {model} | Mode: {permission_mode} | API: {api_url}")
            print("  Type /help for commands\n")
            return

        # Attempt to load local hardware info
        gpu_name = "CPU Only"
        ctx_size = "8K"
        try:
            # We assume repo root is 3 levels up from this file's dir
            repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            config_path = os.path.join(repo_root, "runtime", "llm", "launch_config.json")
            if os.path.exists(config_path):
                import json
                with open(config_path, "r") as f:
                    cfg = json.load(f)
                    gpu_name = cfg.get("gpu_name") or cfg.get("gpu", {}).get("name") or "CPU Only"
                    ctx_size = f"{cfg.get('recommended_ctx_size', 8192) // 1024}K"
        except Exception:
            pass

        # Build welcome content
        header = Text()
        header.append("Atri Code", style="bold bright_white")
        header.append("  ", style="")
        header.append("v1.0", style="dim white")

        table = Table(show_header=False, box=None, padding=(0, 2), expand=False)
        table.add_column(style="dim cyan", width=14)
        table.add_column(style="bright_white")
        table.add_row("Model", model)
        table.add_row("Hardware", gpu_name)
        table.add_row("Context", ctx_size)
        table.add_row("Reasoning", "enabled" if reasoning else "disabled")
        table.add_row("Mode", f"[bold bright_yellow]{permission_mode}[/]")
        table.add_row("API", f"[dim]{api_url}[/]")

        hints = Text()
        hints.append("  Type ", style="dim")
        hints.append("/help", style="bold bright_cyan")
        hints.append(" for commands  •  ", style="dim")
        hints.append("/mode", style="bold bright_cyan")
        hints.append(" to change permissions  •  ", style="dim")
        hints.append("Ctrl+C", style="bold bright_cyan")
        hints.append(" to exit", style="dim")

        from rich.console import Group
        content = Group(header, Text("  Local AI agentic coding infrastructure\n", style="dim"), table, Text(""), hints)

        panel = Panel(
            content,
            border_style="bright_cyan",
            box=ROUNDED,
            padding=(1, 2),
            expand=False,
        )
        self.console.print()
        self.console.print(panel)
        self.console.print()

    # ─── Thinking spinner ──────────────────────────────────────────────────

    def start_thinking(self, turn_number: int = 0) -> None:
        """Show an animated thinking spinner."""
        if not RICH_AVAILABLE:
            print("  Thinking...", end="", flush=True)
            return

        label = Text()
        label.append("  ", style="")
        label.append(f"Turn {turn_number} — ", style="dim") if turn_number else None
        label.append("Thinking", style="italic bright_cyan")
        label.append("...", style="dim")

        self._live = Live(
            label,
            console=self.console,
            refresh_per_second=10,
            transient=True,
        )
        self._live.start()

    def update_thinking(self, phase: str, tool_name: str = "", elapsed: float = 0.0) -> None:
        """Update the thinking display with current phase."""
        if not RICH_AVAILABLE or not self._live:
            return

        label = Text()
        label.append("  ", style="")

        if phase == "tool":
            label.append("Tool: ", style="bright_magenta")
            label.append(f"Running {tool_name}", style="bold magenta")
        elif phase == "thinking":
            label.append("Thinking", style="italic bright_cyan")
        elif phase == "finalizing":
            label.append("Composing response", style="italic bright_green")
        else:
            label.append(phase, style="italic")

        if elapsed > 0:
            label.append(f"  ({elapsed:.1f}s)", style="dim")

        self._live.update(label)

    def stop_thinking(self) -> None:
        """Stop the thinking spinner."""
        if self._live:
            self._live.stop()
            self._live = None
        elif not RICH_AVAILABLE:
            print("\r" + " " * 40 + "\r", end="", flush=True)

    # ─── Tool call rendering ──────────────────────────────────────────────

    def render_tool_call(self, tool_name: str, tool_input: dict | None = None) -> None:
        """Render a tool call in a magenta-bordered panel."""
        if not RICH_AVAILABLE:
            print(f"  Tool: {tool_name}")
            if tool_input:
                for k, v in tool_input.items():
                    val = str(v)[:80]
                    print(f"     {k}: {val}")
            return

        content = Text()
        if tool_input:
            for key, value in tool_input.items():
                content.append(f"  {key}: ", style="bold bright_white")
                val_str = str(value)
                if len(val_str) > 120:
                    val_str = val_str[:117] + "..."
                content.append(f"{val_str}\n", style="white")
        else:
            content.append("  (no arguments)\n", style="dim")

        panel = Panel(
            content,
            title=f"Tool: {tool_name}",
            title_align="left",
            border_style="bright_magenta",
            box=ROUNDED,
            padding=(0, 1),
        )
        self.console.print(panel)

    def render_tool_result(self, tool_name: str, result: str, success: bool = True) -> None:
        """Render a tool result in a green/red panel."""
        if not RICH_AVAILABLE:
            status = "ok" if success else "error"
            print(f"  {status} {tool_name}: {result[:200]}")
            return

        # Truncate long results
        display = result
        if len(display) > 500:
            display = display[:497] + "..."

        style = "green" if success else "red"
        icon = "✓" if success else "✗"

        if not self._compact_mode:
            panel = Panel(
                Text(display, style="white"),
                title=f"{tool_name}",
                title_align="left",
                border_style=style,
                box=ROUNDED,
                padding=(0, 1),
            )
            self.console.print(panel)
        else:
            self.console.print(f"  [bold {style}]{status}[/] {tool_name}", highlight=False)

    # ─── Assistant response ───────────────────────────────────────────────

    def render_user_message(self, text: str) -> None:
        """Render user input with styling."""
        if not RICH_AVAILABLE:
            print(f"\nyou> {text}")
            return
        
        self.console.print()
        self.console.print(
            Text("  you ", style="bold bright_white on dim cyan"),
            Text(f" {text}", style="bright_white"),
        )

    def render_response(self, text: str) -> None:
        """Render assistant response with full markdown support."""
        if not RICH_AVAILABLE:
            print(f"\natri> {text}\n")
            return

        if not text.strip():
            return

        self.console.print()
        self.console.print(
            Text("  atri ", style="bold black on bright_cyan"),
            end="",
        )
        self.console.print()

        # Render as markdown
        md = Markdown(text, code_theme="monokai")
        self.console.print(md, width=min(120, self.console.width - 4))
        self.console.print()

    def print_streaming_token(self, token: str, is_first: bool = False) -> None:
        """Stream response in real-time with markdown rendering."""
        if not RICH_AVAILABLE:
            if is_first:
                print(f"\natri> ", end="", flush=True)
            print(token, end="", flush=True)
            return

        self._stream_buffer += token
        
        if is_first:
            self.console.print()
            self.console.print(Text("  atri ", style="bold black on bright_cyan"))
            self._live = Live(
                Markdown(self._stream_buffer),
                console=self.console,
                refresh_per_second=4,
                transient=False, # We want to keep the final output
            )
            self._live.start()
        elif self._live:
            self._live.update(Markdown(self._stream_buffer))

    def finish_streaming(self) -> None:
        """Finalize streaming output."""
        if not RICH_AVAILABLE:
            print("\n")
            return

        if self._live:
            # Final update to ensure everything is rendered
            self._live.update(Markdown(self._stream_buffer))
            self._live.stop()
            self._live = None
            self._stream_buffer = ""
            self.console.print() # Final spacing

    # ─── Status / summary ─────────────────────────────────────────────────

    def render_turn_summary(
        self,
        turn: int,
        elapsed: float,
        input_tokens: int,
        output_tokens: int,
        tool_calls: int,
        output_tokens_exact: int | None = None,
    ) -> None:
        """Render the post-turn status summary line."""
        if not RICH_AVAILABLE:
            tok_out = output_tokens_exact if output_tokens_exact is not None else output_tokens
            print(f"  [{elapsed:.1f}s] Turn {turn} | in:{input_tokens} out:{tok_out} | tools:{tool_calls}")
            return

        tok_out = output_tokens_exact if output_tokens_exact is not None else output_tokens
        status = Text()
        status.append("  ", style="")
        status.append(f"Turn {turn}", style="bold bright_white")
        status.append("  •  ", style="dim")
        status.append(f"{elapsed:.1f}s", style="bright_cyan")
        status.append("  •  ", style="dim")
        status.append(f"in:{input_tokens}", style="dim bright_blue")
        status.append(" ", style="")
        status.append(f"out:{tok_out}", style="dim bright_green")
        if tool_calls > 0:
            status.append("  •  ", style="dim")
            status.append(f"{tool_calls} tools", style="dim bright_magenta")

        self.console.print(status)

    # ─── Error rendering ──────────────────────────────────────────────────

    def render_error(self, message: str) -> None:
        """Render an error message."""
        if not RICH_AVAILABLE:
            print(f"  ✗ Error: {message}", file=sys.stderr)
            return

        panel = Panel(
            Text(message, style="bright_red"),
            title="Error",
            title_align="left",
            border_style="red",
            box=ROUNDED,
            padding=(0, 1),
        )
        self.console.print(panel, style="")

    def render_warning(self, message: str) -> None:
        """Render a warning message."""
        if RICH_AVAILABLE:
            self.console.print(f"  [bold yellow]warning[/] {message}")
        else:
            print(f"  warning {message}")

    def render_success(self, message: str) -> None:
        """Render a success message."""
        if RICH_AVAILABLE:
            self.console.print(f"  [bold green]ok[/] {message}")
        else:
            print(f"  ok {message}")

    def render_info(self, message: str) -> None:
        """Render an info message."""
        if RICH_AVAILABLE:
            self.console.print(f"  [dim bright_cyan]info[/] {message}")
        else:
            print(f"  info {message}")

    # ─── Plan rendering ───────────────────────────────────────────────────
    
    def render_plan(self, goal: str, steps: list[str]) -> bool:
        """Render a proposed plan and ask for approval."""
        if not RICH_AVAILABLE:
            print(f"\n  Proposed Plan for: {goal}")
            for i, step in enumerate(steps, 1):
                print(f"    {i}. {step}")
            resp = input("\n  Approve this plan? [y/N]: ").strip().lower()
            return resp in {"y", "yes"}

        content = Text()
        content.append(f"Goal: ", style="bold bright_white")
        content.append(f"{goal}\n\n", style="white")
        
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Index", style="bold bright_cyan", justify="right")
        table.add_column("Step", style="white")
        
        for i, step in enumerate(steps, 1):
            table.add_row(f"{i}.", step)
        
        panel = Panel(
            Group(content, table),
            title="Proposed Execution Plan",
            title_align="left",
            border_style="bright_cyan",
            box=ROUNDED,
            padding=(1, 2),
        )
        
        self.console.print()
        self.console.print(panel)
        self.console.print()

        try:
            resp = input("  Approve plan and proceed? (y/n): ").strip().lower()
            return resp in {"y", "yes"}
        except (EOFError, KeyboardInterrupt):
            return False

    # ─── Review rendering ─────────────────────────────────────────────────
    
    def render_review_header(self, path: str) -> None:
        """Render a premium header for the VS Code diff review."""
        if not RICH_AVAILABLE:
            print(f"\n  Reviewing changes for {path} in VS Code...")
            return

        content = Text()
        content.append("  File: ", style="dim")
        content.append(path, style="bold bright_white")
        content.append("\n  Action: ", style="dim")
        content.append("Opening side-by-side diff in VS Code", style="bright_cyan")
        
        panel = Panel(
            content,
            title="Code Review Required",
            title_align="left",
            border_style="bright_cyan",
            box=ROUNDED,
            padding=(1, 2),
        )
        self.console.print()
        self.console.print(panel)
        self.console.print()

    # ─── Permission prompt ────────────────────────────────────────────────
    
    def render_permission_prompt(self, tool_name: str, description: str = "") -> bool:
        """Show an interactive permission prompt. Returns True if allowed."""
        if not RICH_AVAILABLE:
            resp = input(f"  Allow {tool_name}? [y/N]: ").strip().lower()
            return resp in {"y", "yes"}

        content = Text()
        content.append(f"  Tool: ", style="dim")
        content.append(tool_name, style="bold bright_magenta")
        if description:
            content.append(f"\n  {description}", style="dim white")

        panel = Panel(
            content,
            title="Permission Required",
            title_align="left",
            border_style="bright_yellow",
            box=ROUNDED,
            padding=(0, 1),
        )
        self.console.print(panel)

        try:
            resp = input("  Allow? (y/n): ").strip().lower()
            return resp in {"y", "yes"}
        except (EOFError, KeyboardInterrupt):
            return False

    # ─── Slash command help ───────────────────────────────────────────────

    def render_help(self) -> None:
        """Render the slash command help panel."""
        if not RICH_AVAILABLE:
            print("\n  Commands:")
            print("    /help     - Show this help")
            print("    /mode     - Show/change permission mode")
            print("    /compact  - Toggle compact output")
            print("    /model    - Show model info")
            print("    /cost     - Show session token usage")
            print("    /clear    - Clear terminal")
            print("    /exit     - Exit Atri Code\n")
            return

        table = Table(
            show_header=True,
            header_style="bold bright_cyan",
            box=ROUNDED,
            border_style="dim cyan",
            padding=(0, 2),
            title="Atri Code Commands",
            title_style="bold bright_cyan",
        )
        table.add_column("Command", style="bold bright_white", width=16)
        table.add_column("Description", style="white")
        table.add_row("/help", "Show this help")
        table.add_row("/mode [name]", "Show or change permission mode")
        table.add_row("/compact", "Toggle compact output mode")
        table.add_row("/model", "Show model and hardware info")
        table.add_row("/cost", "Show session token usage")
        table.add_row("/clear", "Clear terminal screen")
        table.add_row("/timeline", "Show event timeline")
        table.add_row("/exit", "Exit Atri Code")

        self.console.print()
        self.console.print(table)
        self.console.print()

    # ─── Doctor check rendering ───────────────────────────────────────────

    def render_doctor(self, checks: list[dict[str, Any]]) -> None:
        """Render doctor diagnostics results."""
        if not RICH_AVAILABLE:
            for c in checks:
                status = "✓" if c["ok"] else "✗"
                print(f"  {status} {c['name']} → {c.get('path', '')}")
            return

        self.console.print()
        self.console.print(Text("  Atri Code Doctor", style="bold bright_cyan"))
        self.console.print()

        for item in checks:
            if item["ok"]:
                self.console.print(f"  [bold green]ok[/] {item['name']} [dim]{item.get('path', '')}[/]")
            else:
                self.console.print(f"  [bold red]error[/] {item['name']} [dim]{item.get('path', '')}[/]")
                if item.get("error"):
                    self.console.print(f"    [dim red]{item['error']}[/]")

        self.console.print()

    # ─── Separator ────────────────────────────────────────────────────────

    def separator(self, title: str = "") -> None:
        """Print a horizontal rule."""
        if RICH_AVAILABLE:
            self.console.print(Rule(title, style="dim cyan"))
        else:
            width = os.get_terminal_size((80, 24)).columns
            if title:
                print(f"── {title} " + "─" * max(0, width - len(title) - 4))
            else:
                print("─" * width)

    def clear_screen(self) -> None:
        """Clear the terminal."""
        if RICH_AVAILABLE:
            self.console.clear()
        else:
            print("\033[2J\033[H", end="", flush=True)

    # ─── Model info ───────────────────────────────────────────────────────

    def render_model_info(self, info: dict[str, Any]) -> None:
        """Render model and hardware info panel."""
        if not RICH_AVAILABLE:
            for k, v in info.items():
                print(f"  {k}: {v}")
            return

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="bold bright_cyan", width=20)
        table.add_column(style="bright_white")
        for key, value in info.items():
            table.add_row(key, str(value))

        panel = Panel(
            table,
            title="Model Info",
            title_align="left",
            border_style="bright_cyan",
            box=ROUNDED,
            padding=(1, 1),
        )
        self.console.print()
        self.console.print(panel)
        self.console.print()

    # ─── Cost/token summary ───────────────────────────────────────────────

    def render_cost_summary(
        self,
        total_input: int,
        total_output: int,
        turns: int,
        duration: float,
    ) -> None:
        """Render session cost summary."""
        if not RICH_AVAILABLE:
            print(f"  Session: {turns} turns | ↑{total_input} ↓{total_output} tokens | {duration:.1f}s")
            return

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="dim cyan", width=16)
        table.add_column(style="bright_white")
        table.add_row("Turns", str(turns))
        table.add_row("Input tokens", f"{total_input:,}")
        table.add_row("Output tokens", f"{total_output:,}")
        table.add_row("Total time", f"{duration:.1f}s")

        panel = Panel(
            table,
            title="Session Summary",
            title_align="left",
            border_style="bright_blue",
            box=ROUNDED,
            padding=(0, 1),
        )
        self.console.print(panel)


# ─── Backward-compatible export ────────────────────────────────────────────

# Keep the old TurnStatus import path working
__all__ = ["RichTUI", "TurnStatus", "TIMELINE_VERBOSITY_LEVELS"]
