"""
Worktree management for parallel conversation flows.

Handles creation, tracking, and cleanup of git worktrees associated with conversations.
Enables isolated work contexts for forked conversations.
"""

from __future__ import annotations

import subprocess
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass
import json

logger = logging.getLogger(__name__)


@dataclass
class WorktreeInfo:
    """Information about a git worktree linked to a conversation."""
    path: str
    conversation_id: str
    branch: Optional[str] = None
    is_dirty: bool = False


class WorktreeManager:
    """Manages git worktrees for isolated conversation contexts."""

    def __init__(self, repo_root: Optional[str] = None):
        """
        Initialize worktree manager.
        
        Args:
            repo_root: Root directory of git repository
        """
        self.repo_root = Path(repo_root or Path.cwd())
        self._worktrees: Dict[str, WorktreeInfo] = {}

    def _run_git_command(self, *args: str) -> str:
        """Run a git command and return output."""
        try:
            result = subprocess.run(
                ["git"] + list(args),
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Git command failed: {result.stderr}")
            return result.stdout.strip()
        except Exception as e:
            logger.error(f"Git command error: {e}")
            raise

    def is_dirty(self, path: Optional[str] = None) -> bool:
        """Check if worktree has uncommitted changes."""
        try:
            work_dir = path or self.repo_root
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return bool(result.stdout.strip())
        except Exception as e:
            logger.warning(f"Failed to check dirty status: {e}")
            return False

    def create_worktree(
        self, conversation_id: str, worktree_name: str, base_branch: str = "master"
    ) -> WorktreeInfo:
        """
        Create a new git worktree for a conversation.
        
        Args:
            conversation_id: Conversation ID to link to worktree
            worktree_name: Name/path suffix for the worktree
            base_branch: Base branch to create worktree from
            
        Returns:
            WorktreeInfo describing the created worktree
        """
        worktree_path = self.repo_root / ".worktrees" / worktree_name
        
        try:
            # Create worktrees directory if needed
            (self.repo_root / ".worktrees").mkdir(parents=True, exist_ok=True)
            
            # Create new worktree
            branch_name = f"conv-{conversation_id}"
            self._run_git_command(
                "worktree", "add", "-b", branch_name, str(worktree_path), base_branch
            )
            
            info = WorktreeInfo(
                path=str(worktree_path),
                conversation_id=conversation_id,
                branch=branch_name,
                is_dirty=False,
            )
            self._worktrees[worktree_name] = info
            logger.info(f"Created worktree {worktree_name} for conversation {conversation_id}")
            return info
        except Exception as e:
            logger.error(f"Failed to create worktree: {e}")
            raise

    def remove_worktree(self, worktree_name: str, force: bool = False) -> bool:
        """
        Remove a worktree.
        
        Args:
            worktree_name: Name of worktree to remove
            force: Force removal even if dirty
            
        Returns:
            True if removal succeeded
        """
        try:
            if worktree_name not in self._worktrees:
                logger.warning(f"Worktree {worktree_name} not tracked")
                return False

            info = self._worktrees[worktree_name]
            cmd = ["worktree", "remove", info.path]
            if force:
                cmd.append("--force")
            
            self._run_git_command(*cmd)
            del self._worktrees[worktree_name]
            logger.info(f"Removed worktree {worktree_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to remove worktree: {e}")
            return False

    def list_worktrees(self) -> List[WorktreeInfo]:
        """List all tracked worktrees."""
        for name, info in list(self._worktrees.items()):
            info.is_dirty = self.is_dirty(info.path)
        return list(self._worktrees.values())

    def get_worktree(self, worktree_name: str) -> Optional[WorktreeInfo]:
        """Get information about a specific worktree."""
        if worktree_name not in self._worktrees:
            return None
        info = self._worktrees[worktree_name]
        info.is_dirty = self.is_dirty(info.path)
        return info

    def cleanup_dirty_worktrees(self, auto_clean: bool = False) -> Dict[str, bool]:
        """
        Check for and optionally clean up dirty worktrees.
        
        Args:
            auto_clean: Automatically clean without prompting
            
        Returns:
            Dict mapping worktree_name -> cleaned (True/False)
        """
        results = {}
        for name, info in self._worktrees.items():
            if self.is_dirty(info.path):
                if auto_clean:
                    results[name] = self.remove_worktree(name, force=True)
                else:
                    results[name] = False  # Caller will prompt
        return results
