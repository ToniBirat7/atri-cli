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
from dataclasses import dataclass
from typing import Any, Optional

# Rich imports — gracefully degrade if not available
try:
    from rich.console import Console, Group
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.live import Live
    from rich.syntax import Syntax
    from rich.table import Table
    from rich.text import Text
    from rich.theme import Theme
    from rich.rule import Rule
    from rich.box import ROUNDED, HEAVY

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
        model: str = "local model",
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

    # Human-readable verb per tool (Claude-Code style action labels).
    _TOOL_VERBS = {
        "read_text_file": "Read", "read_file": "Read", "read_multiple_files": "Read",
        "write_file": "Write", "write_json_file": "Write", "create_file": "Write",
        "append_file": "Append",
        "edit_file": "Update", "edit_diff": "Update", "edit_file_hashline": "Update",
        "list_directory": "List", "directory_tree": "Tree", "get_file_info": "Stat",
        "grep_codebase": "Search", "search_files": "Search", "search_symbols": "Symbols",
        "bash_exec": "Bash", "get_repo_map": "Map", "view_git_diff": "Diff",
        "delete_path": "Delete", "move_file": "Move", "create_directory": "Mkdir",
        "create_project": "Scaffold", "search_web": "Web", "fetch_url": "Fetch",
        "todo_write": "Plan", "propose_plan": "Plan", "set_allowed_directory": "Workspace",
    }

    @classmethod
    def _tool_key_arg(cls, tool_name: str, tool_input: dict) -> str:
        """The single most relevant argument to show next to the verb."""
        ti = tool_input or {}
        for key in ("target_file_path", "path", "file_path", "target_path",
                    "target_directory_path", "command", "cmd", "pattern", "query", "url"):
            if ti.get(key):
                val = str(ti[key])
                return val if len(val) <= 72 else "…" + val[-71:]
        # move: src → dst
        if ti.get("source_path"):
            return f"{ti.get('source_path')} → {ti.get('destination_path', '?')}"
        return ""

    def render_tool_call(self, tool_name: str, tool_input: dict | None = None) -> None:
        """Render a tool call as a single compact action line: ● Verb arg."""
        verb = self._TOOL_VERBS.get(tool_name, tool_name)
        arg = self._tool_key_arg(tool_name, tool_input or {})
        if not RICH_AVAILABLE:
            print(f"  • {verb} {arg}".rstrip())
            return
        line = Text("  ● ", style="bold bright_magenta")
        line.append(verb, style="bold bright_white")
        if arg:
            line.append(f"  {arg}", style="dim")
        self.console.print(line, highlight=False)

    @staticmethod
    def _detect_language(tool_name: str, result: str, tool_input: dict | None = None) -> str | None:
        """Infer a Rich Syntax language for tool output, or None for plain text."""
        # File reads: infer from path argument
        if tool_name in ("read_text_file", "read_file", "write_file", "edit_file", "append_file"):
            path = ""
            if tool_input:
                path = str(
                    tool_input.get("target_file_path")
                    or tool_input.get("path", "")
                )
            ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
            lang_map = {
                "py": "python", "ts": "typescript", "tsx": "typescript",
                "js": "javascript", "jsx": "javascript", "rs": "rust",
                "go": "go", "sh": "bash", "bash": "bash", "zsh": "bash",
                "json": "json", "yaml": "yaml", "yml": "yaml",
                "toml": "toml", "html": "html", "css": "css",
                "md": "markdown", "sql": "sql", "c": "c", "cpp": "cpp",
                "java": "java", "rb": "ruby", "php": "php",
            }
            if ext in lang_map:
                return lang_map[ext]

        stripped = result.strip()
        # Diff output
        if stripped.startswith("---") or stripped.startswith("@@") or stripped.startswith("diff --git"):
            return "diff"
        # JSON object or array
        if (stripped.startswith("{") and stripped.endswith("}")) or \
           (stripped.startswith("[") and stripped.endswith("]")):
            return "json"
        # Shell output with header from bash_exec
        if tool_name == "bash_exec" or stripped.startswith("[exit:"):
            return "bash"
        # grep_codebase / search_symbols results as JSON
        if tool_name in ("grep_codebase", "search_symbols", "get_repo_map", "directory_tree"):
            return "json" if stripped.startswith("{") else None
        return None

    @staticmethod
    def _result_summary(tool_name: str, result: str) -> str:
        """One-line summary of a tool result (count, output head, or 'ok')."""
        import json as _json
        s = (result or "").strip()
        try:
            obj = _json.loads(s)
            if isinstance(obj, dict):
                if isinstance(obj.get("line_count"), int):
                    return f"{obj['line_count']} lines"
                for key, noun in (("matches", "matches"), ("entries", "items"),
                                  ("symbols", "symbols"), ("results", "results")):
                    if isinstance(obj.get(key), list):
                        return f"{len(obj[key])} {noun}"
                if "output" in obj:
                    out = str(obj["output"]).strip().splitlines()
                    head = out[0] if out else ""
                    return (head[:78] + "…") if len(head) > 78 else (head or "ok")
                if obj.get("applied") is True:
                    return f"applied ({obj.get('matches', 1)} match)"
                if obj.get("ok") is True:
                    return "ok"
        except (ValueError, TypeError):
            pass
        # Large results get distilled/truncated so json.loads fails — extract
        # common signals by regex from whatever prefix we have.
        import re as _re
        m = _re.search(r'"line_count"\s*:\s*(\d+)', s)
        if m:
            return f"{m.group(1)} lines"
        m = _re.search(r'"path"\s*:\s*"([^"]+)"', s)
        if m:
            return f"read {m.group(1)}"
        if "Full result at:" in s or "truncated" in s.lower():
            return "large result (truncated)"
        first = s.splitlines()[0] if s else ""
        return (first[:78] + "…") if len(first) > 78 else (first or "done")

    def render_tool_result(
        self,
        tool_name: str,
        result: str,
        success: bool = True,
        tool_input: dict | None = None,
    ) -> None:
        """Render a tool result as a compact continuation line under the call.

        Success → a dim `└ <summary>`. Errors are always shown (a few lines).
        In 'debug' timeline verbosity, the full syntax-highlighted panel is shown.
        """
        if not RICH_AVAILABLE:
            print(f"    └ {'ok' if success else 'error'}: {(result or '')[:160]}")
            return

        if not success:
            # Errors matter — surface the message (first few lines) in red.
            err_lines = (result or "Unknown error").strip().splitlines()[:4]
            line = Text("    └ ", style="dim")
            line.append("error: ", style="bold red")
            line.append(" ".join(l.strip() for l in err_lines)[:200], style="red")
            self.console.print(line, highlight=False)
            return

        # Compact success summary (default).
        if self.timeline_verbosity != "debug":
            line = Text("    └ ", style="dim")
            line.append(self._result_summary(tool_name, result), style="green")
            self.console.print(line, highlight=False)
            return

        # debug verbosity: full panel with syntax highlighting.
        max_chars = 2000
        display = result if len(result) <= max_chars else result[:max_chars] + f"\n… ({len(result) - max_chars} chars omitted)"
        lang = self._detect_language(tool_name, result, tool_input)
        content = Syntax(display, lang, theme="monokai", word_wrap=True, background_color="default") if lang else Text(display, style="white")
        self.console.print(Panel(content, title=f"[OK] {tool_name}", title_align="left",
                                 border_style="green", box=ROUNDED, padding=(0, 1)))

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
                print("\natri> ", end="", flush=True)
            print(token, end="", flush=True)
            return

        if is_first:
            # Start fresh — drop any buffer left over from a previous turn whose
            # Live was stopped early (e.g. by stop_thinking on a mid-stream
            # confirmation), so stale text isn't prepended to this response.
            self._stream_buffer = token
            self.console.print()
            self.console.print(Text("  atri ", style="bold black on bright_cyan"))
            self._live = Live(
                Markdown(self._stream_buffer),
                console=self.console,
                refresh_per_second=4,
                transient=False, # We want to keep the final output
            )
            self._live.start()
        else:
            self._stream_buffer += token
            if self._live:
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
            self.console.print() # Final spacing
        # Always clear the buffer, even if _live was already stopped early.
        self._stream_buffer = ""

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
            print(f"  [ERROR] {message}", file=sys.stderr)
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
        content.append("Goal: ", style="bold bright_white")
        content.append(f"{goal}\n\n", style="white")
        
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Index", style="bold bright_cyan", justify="right")
        table.add_column("Step", style="white")
        
        for i, step in enumerate(steps, 1):
            table.add_row(f"{i}.", step)
            
        panel = Panel(
            Group(content, table),
            title="Proposed Plan",
            title_align="left",
            border_style="bright_cyan",
            box=ROUNDED,
            padding=(0, 1),
        )
        self.console.print(panel)
        
        try:
            resp = input("\n  Approve this plan? (y/n): ").strip().lower()
            return resp in {"y", "yes"}
        except (EOFError, KeyboardInterrupt):
            return False

    def render_progress(self, current: int, total: int, description: str = "Progress") -> None:
        """Render a clean ASCII progress bar."""
        if not RICH_AVAILABLE:
            pct = int((current / total) * 100)
            print(f"  [{current}/{total}] {description} ({pct}%)")
            return

        percentage = current / total
        bar_width = 30
        filled_len = int(bar_width * percentage)
        bar = "━" * filled_len + "─" * (bar_width - filled_len)
        
        text = Text()
        text.append("  ", style="")
        text.append(f"{current}/{total}", style="bold bright_white")
        text.append(" [", style="dim")
        text.append(bar, style="bright_cyan")
        text.append("] ", style="dim")
        text.append(description, style="white")
        
        self.console.print(text)
    # ─── Diff renderer ───────────────────────────────────────────────────

    def render_diff(self, diff_text: str, title: str = "Diff") -> None:
        """Render a unified diff inline with Rich color coding."""
        if not RICH_AVAILABLE:
            print(diff_text)
            return

        if not diff_text or not diff_text.strip():
            self.console.print("  [dim](no diff)[/dim]")
            return

        from rich.console import Group as RichGroup

        lines: list[Text] = []
        for raw_line in diff_text.splitlines():
            if raw_line.startswith("+++") or raw_line.startswith("---"):
                lines.append(Text(raw_line, style="bold white"))
            elif raw_line.startswith("@@"):
                lines.append(Text(raw_line, style="bold cyan"))
            elif raw_line.startswith("+"):
                lines.append(Text(raw_line, style="bright_green"))
            elif raw_line.startswith("-"):
                lines.append(Text(raw_line, style="bright_red"))
            else:
                lines.append(Text(raw_line, style="dim white"))

        panel = Panel(
            RichGroup(*lines),
            title=title,
            title_align="left",
            border_style="yellow",
            box=ROUNDED,
            padding=(0, 1),
        )
        self.console.print(panel)

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
    
    def render_permission_prompt(
        self,
        tool_name: str,
        description: str = "",
        risk_tier: str = "yellow",
    ) -> bool:
        """Show an interactive permission prompt with risk-tier coloring. Returns True if allowed."""
        _tier_color = {"red": "bright_red", "yellow": "bright_yellow", "green": "bright_green"}
        _tier_icon = {"red": "⛔ DANGER", "yellow": "⚠  Confirm", "green": "✓ Safe"}
        color = _tier_color.get(risk_tier, "bright_yellow")
        icon = _tier_icon.get(risk_tier, "⚠  Confirm")

        if not RICH_AVAILABLE:
            resp = input(f"  [{icon}] Allow {tool_name}? [y/N]: ").strip().lower()
            return resp in {"y", "yes"}

        content = Text()
        content.append(f"  {icon}  ", style=f"bold {color}")
        content.append(tool_name, style="bold bright_magenta")
        if description:
            content.append(f"\n  {description}", style="dim white")
        content.append("\n\n  Risk tier: ", style="dim")
        content.append(risk_tier.upper(), style=f"bold {color}")
        content.append("   Press ", style="dim")
        content.append("y", style="bold bright_green")
        content.append(" to allow, ", style="dim")
        content.append("n", style="bold bright_red")
        content.append(" to deny", style="dim")

        panel = Panel(
            content,
            title="Permission Required",
            title_align="left",
            border_style=color,
            box=HEAVY,
            padding=(0, 1),
        )
        self.console.print(panel)

        try:
            resp = input("  > ").strip().lower()
            return resp in {"y", "yes"}
        except (EOFError, KeyboardInterrupt):
            return False

    @staticmethod
    def _format_tool_confirmation_detail(tool_name: str, tool_input: dict) -> str:
        """Human-readable preview of what a tool will do, for the confirm prompt."""
        ti = tool_input or {}

        def _clip(value: Any, limit: int = 400) -> str:
            text = str(value)
            return text if len(text) <= limit else text[:limit] + " …"

        if tool_name in {"edit_file", "edit_file_hashline"}:
            old = ti.get("exact_text_to_replace") or ti.get("old_text") or ti.get("edits") or ""
            new = ti.get("new_text_content") or ti.get("new_text") or ""
            path = ti.get("target_file_path") or ti.get("path") or "?"
            lines = [f"file: {path}"]
            if old:
                lines += [f"- {l}" for l in _clip(old).splitlines()[:8]]
            if new:
                lines += [f"+ {l}" for l in _clip(new).splitlines()[:8]]
            return "\n".join(lines)
        if tool_name == "edit_diff":
            return f"file: {ti.get('target_file_path', '?')}\n{_clip(ti.get('diff', ''))}"
        if tool_name in {"write_file", "write_json_file", "append_file", "create_file"}:
            body = ti.get("content") or ti.get("data") or ""
            return f"file: {ti.get('target_file_path', '?')}\n{_clip(body)}"
        if tool_name in {"delete_path", "delete_file", "remove_file"}:
            rec = " (recursive)" if ti.get("recursive") else ""
            return f"delete: {ti.get('target_path') or ti.get('path') or '?'}{rec}"
        if tool_name in {"move_file", "rename_file"}:
            return f"{ti.get('source_path', '?')}  →  {ti.get('destination_path', '?')}"
        if tool_name in {"bash_exec", "run_shell", "run_command"}:
            return f"$ {_clip(ti.get('command') or ti.get('cmd') or '?')}"
        if tool_name in {"create_directory", "create_project"}:
            return f"create: {ti.get('target_directory_path') or ti.get('target_project_path') or '?'}"
        # Fallback: dump args
        return "\n".join(f"{k}: {_clip(v, 200)}" for k, v in ti.items()) or "(no arguments)"

    def render_tool_confirmation(
        self, tool_name: str, tool_input: dict, risk_tier: str = "yellow"
    ) -> str:
        """Interactive confirmation for a state-changing tool.

        Returns 'allow' (run once), 'always' (auto-approve this tool for the
        session), or 'deny'.
        """
        _tier_color = {"red": "bright_red", "yellow": "bright_yellow", "green": "bright_green"}
        _tier_icon = {"red": "⛔ Destructive", "yellow": "✎ Edit", "green": "✓ Safe"}
        color = _tier_color.get(risk_tier, "bright_yellow")
        icon = _tier_icon.get(risk_tier, "⚠ Confirm")
        detail = self._format_tool_confirmation_detail(tool_name, tool_input)

        if not RICH_AVAILABLE:
            print(f"\n  [{icon}] {tool_name}\n  {detail}")
            resp = input("  Allow? [y]es / [a]lways / [N]o: ").strip().lower()
            if resp in {"a", "always"}:
                return "always"
            return "allow" if resp in {"y", "yes"} else "deny"

        content = Text()
        content.append(f"{icon}  ", style=f"bold {color}")
        content.append(tool_name, style="bold bright_magenta")
        if detail:
            content.append("\n\n")
            content.append(detail, style="white")
        panel = Panel(
            content,
            title="Confirm tool call",
            title_align="left",
            border_style=color,
            box=HEAVY,
            padding=(0, 1),
        )
        self.console.print()
        self.console.print(panel)
        hint = Text("  ")
        hint.append("y", style="bold bright_green")
        hint.append(" allow once    ", style="dim")
        hint.append("a", style="bold bright_cyan")
        hint.append(" always allow    ", style="dim")
        hint.append("n", style="bold bright_red")
        hint.append(" deny", style="dim")
        self.console.print(hint)
        try:
            resp = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "deny"
        if resp in {"a", "always"}:
            return "always"
        return "allow" if resp in {"y", "yes"} else "deny"

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
                status = "[OK]" if c["ok"] else "[ERROR]"
                print(f"  {status} {c['name']} → {c.get('path', '')}")
            return

        self.console.print()
        self.console.print(Text("  Atri Code Doctor", style="bold bright_cyan"))
        self.console.print()

        for item in checks:
            if item["ok"]:
                self.console.print(f"  [bold green][OK][/] {item['name']} [dim]{item.get('path', '')}[/]")
            else:
                self.console.print(f"  [bold red][ERROR][/] {item['name']} [dim]{item.get('path', '')}[/]")
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
