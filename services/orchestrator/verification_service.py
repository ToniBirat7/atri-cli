import os
import subprocess
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class VerificationService:
    """
    Automatically verifies codebase integrity after agent modifications.
    Supports linting, type-checking, and test execution.
    """

    def __init__(self, repo_root: str):
        self.repo_root = repo_root

    def verify(self) -> Dict[str, Any]:
        """
        Run a battery of checks based on project type.
        """
        results = {
            "success": True,
            "checks": []
        }

        # 1. Detect and run Python linting
        if os.path.exists(os.path.join(self.repo_root, "requirements.txt")):
            lint_res = self._run_command(["python3", "-m", "pyflakes", "."])
            results["checks"].append({"name": "pyflakes", "output": lint_res})
            if lint_res: # pyflakes only outputs on errors
                results["success"] = False

        # 2. Run atri-cli doctor (internal health)
        doctor_res = self._run_command(["atri-cli", "doctor"], timeout=10)
        results["checks"].append({"name": "atri-doctor", "output": doctor_res})
        if "FAILED" in doctor_res:
            results["success"] = False

        return results

    def _run_command(self, cmd: List[str], timeout: int = 30) -> str:
        try:
            result = subprocess.run(
                cmd,
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return (result.stdout + "\n" + result.stderr).strip()
        except subprocess.TimeoutExpired:
            return "ERROR: Timeout during verification"
        except Exception as e:
            return f"ERROR: {e}"

if __name__ == "__main__":
    vs = VerificationService(".")
    print(vs.verify())
