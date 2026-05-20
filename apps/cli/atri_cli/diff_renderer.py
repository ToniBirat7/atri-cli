"""
Inline diff viewer for atri-cli TUI.
Renders unified diffs with ANSI color coding inline before approve/reject.
Inspired by Pi's edit diff preview.
"""
from __future__ import annotations
import difflib
from typing import Optional

# ANSI colors
RED = "\033[31m"
GREEN = "\033[32m"
CYAN = "\033[36m"
DIM = "\033[2m"
RESET = "\033[0m"
BOLD = "\033[1m"


def render_unified_diff(
    before: str,
    after: str,
    filename: str = "",
    context_lines: int = 3,
    max_lines: int = 60,
) -> str:
    """
    Render a color-coded unified diff between before and after text.
    Returns an ANSI-colored string ready to print.
    """
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        before_lines, after_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        n=context_lines,
    ))

    if not diff:
        return f"{DIM}(no changes){RESET}"

    output_lines: list[str] = []
    for line in diff[:max_lines]:
        if line.startswith("---") or line.startswith("+++"):
            output_lines.append(f"{BOLD}{CYAN}{line.rstrip()}{RESET}")
        elif line.startswith("@@"):
            output_lines.append(f"{CYAN}{line.rstrip()}{RESET}")
        elif line.startswith("+"):
            output_lines.append(f"{GREEN}{line.rstrip()}{RESET}")
        elif line.startswith("-"):
            output_lines.append(f"{RED}{line.rstrip()}{RESET}")
        else:
            output_lines.append(f"{DIM}{line.rstrip()}{RESET}")

    if len(diff) > max_lines:
        output_lines.append(f"{DIM}... ({len(diff) - max_lines} more lines){RESET}")

    return "\n".join(output_lines)


def render_diff_for_tool_result(
    tool_name: str,
    tool_input: dict,
    before_content: Optional[str] = None,
) -> Optional[str]:
    """
    If the tool is an edit tool and we have before content, render a diff.
    Returns None if not applicable.
    """
    if tool_name not in ("edit_file", "edit_diff"):
        return None

    path = tool_input.get("target_file_path", tool_input.get("path", ""))

    if tool_name == "edit_file" and before_content is not None:
        old_text = tool_input.get("exact_text_to_replace", tool_input.get("old_text", ""))
        new_text = tool_input.get("new_text_content", tool_input.get("new_text", ""))
        if old_text and new_text:
            after_content = before_content.replace(old_text, new_text, 1)
            return render_unified_diff(before_content, after_content, filename=path)

    return None
