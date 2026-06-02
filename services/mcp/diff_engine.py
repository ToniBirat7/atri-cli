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

        try:
            # -u for unified
            # -s for silent
            # --fuzz=3 to allow some mismatch in context
            # -p0 to treat paths literally or rely on the fact that we provide the file path
            result = subprocess.run(
                ["patch", "-u", "-s", "--fuzz=3", tmp_orig_path, "-i", tmp_diff_path],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                logger.error(f"Patch command failed: {result.stderr}")
                # Fallback: try without fuzz if the system patch doesn't support it
                if "invalid option -- -" in result.stderr or "fuzz" in result.stderr:
                     result = subprocess.run(
                        ["patch", "-u", "-s", tmp_orig_path, "-i", tmp_diff_path],
                        capture_output=True,
                        text=True
                    )
                     if result.returncode != 0:
                         return None
                else:
                    return None
            
            with open(tmp_orig_path, "r") as f:
                return f.readlines()
        finally:
            if os.path.exists(tmp_diff_path): os.remove(tmp_diff_path)
            if os.path.exists(tmp_orig_path): os.remove(tmp_orig_path)

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
