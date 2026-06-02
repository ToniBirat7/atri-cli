"""Smoke tests — Phase 0 baseline. More suites added in Phase 5."""
import importlib
import sys
import os

# Allow direct invocation: cd services/orchestrator && pytest tests/
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_config_loads():
    """OrchestratorConfig.from_env() must not raise with defaults."""
    import config as cfg
    c = cfg.OrchestratorConfig.from_env()
    assert c.llm.base_url
    assert c.agent_loop.max_turns > 0


def test_prompt_policy_profiles_exist():
    """prompt_policy must expose at least general-purpose."""
    import prompt_policy as pp
    assert "general-purpose" in pp.VALID_PROMPT_PROFILES


def test_no_orphan_imports():
    """Deleted modules must not be importable from the package."""
    for mod in ("verification_service", "worktree_manager"):
        try:
            importlib.import_module(mod)
            # if it imports, it shouldn't exist as a local file
            import pathlib
            local = pathlib.Path(__file__).parent.parent / f"{mod}.py"
            assert not local.exists(), f"{mod}.py still exists on disk"
        except ModuleNotFoundError:
            pass  # expected
