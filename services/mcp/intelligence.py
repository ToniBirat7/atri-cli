import os
import logging
from typing import Any, Dict, List, Optional
from mcp.server.fastmcp import FastMCP

# We need to import the IndexManager and RepoMap from orchestrator
# But since MCP might run in a separate process, we should handle paths carefully
# For now, we assume standard production layout

logger = logging.getLogger(__name__)
mcp = FastMCP("intelligence")

# Configuration (In production, these come from env or config)
DB_PATH = os.environ.get("CODE_INDEX_DB", "runtime/state/code_index.db")
REPO_ROOT = os.environ.get("REPO_ROOT", ".")

def get_index_manager():
    from index_manager import IndexManager
    return IndexManager(DB_PATH, REPO_ROOT)

def get_repo_map_service():
    from repo_map import RepoMap
    return RepoMap(DB_PATH, REPO_ROOT)

@mcp.tool
def search_symbols(query: str) -> List[Dict[str, Any]]:
    """
    Search for functions, classes, or methods across the entire codebase.
    Returns location (file, line) and signature for matching symbols.
    """
    manager = get_index_manager()
    return manager.search_symbols(query)

@mcp.tool
def get_repo_map(max_depth: int = 3) -> str:
    """
    Get a high-level overview of the project structure and symbol signatures.
    Useful for understanding the codebase layout and finding entry points.
    """
    # First, ensure index is up to date
    manager = get_index_manager()
    manager.index_project()
    
    service = get_repo_map_service()
    return service.generate_map(max_depth=max_depth)

@mcp.tool
def propose_plan(steps: List[str], goal: str) -> str:
    """
    Propose a multi-step plan to solve a complex task. 
    The system will pause and request user approval before any further actions are taken.
    'steps' should be a list of clear, actionable tasks.
    'goal' is the high-level objective of the plan.
    """
    # This is a 'virtual' tool that triggers a pause in the orchestrator
    return "Plan submitted for approval. Awaiting user response."

if __name__ == "__main__":
    mcp.run()
