import os
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

class DiffEngine:
    """
    Applies Unified Diffs (UDIFF) to local files.
    This is more robust and token-efficient than whole-file rewrites.
    """

    @staticmethod
    def apply_diff(file_path: str, diff_content: str) -> bool:
        """
        Applies a unified diff to a file.
        Returns True if successful, False otherwise.
        """
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return False

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                original_lines = f.readlines()

            # Clean up diff_content (sometimes LLMs add extra text)
            diff_lines = diff_content.strip().splitlines()
            # Ensure each line ends with \n for patch application
            diff_lines = [line + "\n" for line in diff_lines]

            # Use difflib to apply the patch
            # Note: difflib doesn't have a direct 'apply_patch', 
            # so we'll use a simple hunk-based approach or 
            # a third-party library if needed.
            # For v2-MVP, we'll implement a robust hunk applier.
            
            new_lines = DiffEngine._patch_lines(original_lines, diff_lines)
            
            if new_lines is None:
                return False

            with open(file_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            
            return True

        except Exception as e:
            logger.error(f"Failed to apply diff to {file_path}: {e}")
            return False

    @staticmethod
    def get_preview(file_path: str, diff_content: str) -> Optional[str]:
        """
        Calculates the new content of a file after applying a diff, without writing to disk.
        Returns the new content as a string, or None if patching failed.
        """
        if not os.path.exists(file_path):
            logger.error(f"File not found for preview: {file_path}")
            return None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                original_lines = f.readlines()

            # Clean up diff_content
            diff_lines = diff_content.strip().splitlines()
            diff_lines = [line + "\n" for line in diff_lines]

            new_lines = DiffEngine._patch_lines(original_lines, diff_lines)
            
            if new_lines is None:
                return None

            return "".join(new_lines)

        except Exception as e:
            logger.error(f"Failed to calculate preview for {file_path}: {e}")
            return None

    @staticmethod
    def _patch_lines(original: List[str], diff: List[str]) -> Optional[List[str]]:
        """
        Simple but robust unified diff patcher using system 'patch' command.
        """
        import subprocess
        import tempfile

        # Pre-process diff: Ensure it has headers if they are missing
        # LLMs often omit headers and just give hunks.
        has_headers = any(line.startswith('--- ') for line in diff[:5])
        if not has_headers:
            # Inject dummy headers so 'patch' is happy
            # We don't know the 'old' filename for sure in the hunk, 
            # but 'patch' usually takes the one from command line or -i
            header = [
                "--- a/file\n",
                "+++ b/file\n"
            ]
            diff = header + diff

        with tempfile.NamedTemporaryFile(mode='w', suffix='.diff', delete=False) as tmp_diff:
            tmp_diff.writelines(diff)
            tmp_diff_path = tmp_diff.name

        with tempfile.NamedTemporaryFile(mode='w', suffix='.orig', delete=False) as tmp_orig:
            tmp_orig.writelines(original)
            tmp_orig_path = tmp_orig.name

        # Exact context match (--fuzz=0): a coding agent has read the file, so the
        # diff context should match precisely. Refusing a fuzzy match is far safer
        # than letting `patch` relocate a hunk to the wrong place and silently
        # corrupt the file. We validate with --dry-run first and only apply if it
        # would succeed cleanly (avoids non-atomic partial application).
        base_cmd = ["patch", "-u", "-s", "--fuzz=0", tmp_orig_path, "-i", tmp_diff_path]
        try:
            dry = subprocess.run(base_cmd + ["--dry-run"], capture_output=True, text=True)
            if dry.returncode != 0:
                logger.error("Diff does not apply cleanly (dry-run): %s", (dry.stderr or dry.stdout).strip())
                return None
            result = subprocess.run(base_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error("Patch apply failed after clean dry-run: %s", result.stderr.strip())
                return None
            with open(tmp_orig_path, "r") as f:
                return f.readlines()
        finally:
            # Clean the temp inputs plus any .orig/.rej siblings patch may leave.
            for _p in (tmp_diff_path, tmp_orig_path, tmp_orig_path + ".orig", tmp_orig_path + ".rej"):
                if os.path.exists(_p):
                    os.remove(_p)

if __name__ == "__main__":
    # Test
    test_file = "test_diff.txt"
    with open(test_file, "w") as f:
        f.write("line 1\nline 2\nline 3\n")
    
    diff = """--- test_diff.txt
+++ test_diff.txt
@@ -1,3 +1,3 @@
 line 1
-line 2
+line 2 modified
 line 3
"""
    if DiffEngine.apply_diff(test_file, diff):
        with open(test_file, "r") as f:
            print(f"Result: {f.read()}")
    os.remove(test_file)
