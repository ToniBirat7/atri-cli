"""Tests for worktree management."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
from orchestrator.worktree_manager import WorktreeManager, WorktreeInfo


def test_worktree_info_creation():
    """Test WorktreeInfo dataclass creation."""
    info = WorktreeInfo(
        path="/tmp/worktree",
        conversation_id="conv_123",
        branch="conv-conv_123",
        is_dirty=False,
    )
    assert info.path == "/tmp/worktree"
    assert info.conversation_id == "conv_123"
    assert info.branch == "conv-conv_123"
    assert info.is_dirty is False


def test_worktree_manager_initialization():
    """Test WorktreeManager initialization."""
    manager = WorktreeManager(repo_root="/tmp/repo")
    assert manager.repo_root == Path("/tmp/repo")
    assert len(manager.list_worktrees()) == 0


def test_worktree_manager_is_dirty_check():
    """Test checking if worktree is dirty."""
    manager = WorktreeManager()
    
    # Mock subprocess to simulate clean worktree
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(stdout="", returncode=0)
        is_dirty = manager.is_dirty("/tmp/test")
        assert is_dirty is False


def test_worktree_manager_is_dirty_with_changes():
    """Test checking dirty status with uncommitted changes."""
    manager = WorktreeManager()
    
    # Mock subprocess to simulate dirty worktree
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(stdout="M file.txt\n", returncode=0)
        is_dirty = manager.is_dirty("/tmp/test")
        assert is_dirty is True


def test_worktree_cleanup_no_dirty():
    """Test cleanup when no dirty worktrees exist."""
    manager = WorktreeManager()
    with patch.object(manager, "is_dirty", return_value=False):
        results = manager.cleanup_dirty_worktrees(auto_clean=False)
        assert len(results) == 0


def test_worktree_list_updates_dirty_status():
    """Test that list_worktrees updates dirty status."""
    manager = WorktreeManager()
    # Manually add a worktree
    info = WorktreeInfo(
        path="/tmp/test",
        conversation_id="conv_123",
        branch="test-branch",
        is_dirty=False,
    )
    manager._worktrees["test"] = info
    
    with patch.object(manager, "is_dirty", return_value=True):
        worktrees = manager.list_worktrees()
        assert len(worktrees) == 1
        assert worktrees[0].is_dirty is True


def test_worktree_get_worktree():
    """Test getting a specific worktree."""
    manager = WorktreeManager()
    info = WorktreeInfo(
        path="/tmp/test",
        conversation_id="conv_123",
        branch="test-branch",
        is_dirty=False,
    )
    manager._worktrees["test"] = info
    
    retrieved = manager.get_worktree("test")
    assert retrieved is not None
    assert retrieved.conversation_id == "conv_123"


def test_worktree_get_nonexistent():
    """Test getting nonexistent worktree returns None."""
    manager = WorktreeManager()
    retrieved = manager.get_worktree("nonexistent")
    assert retrieved is None


def test_worktree_parser_support(monkeypatch):
    """Test that CLI parser supports worktree commands."""
    from tarbar_cli.main import _build_parser
    
    parser = _build_parser()
    
    # Test worktree list command
    args = parser.parse_args(["worktrees", "list"])
    assert args.command == "worktrees"
    assert args.worktrees_command == "list"
    
    # Test worktree clean command
    args = parser.parse_args(["worktrees", "clean"])
    assert args.command == "worktrees"
    assert args.worktrees_command == "clean"
