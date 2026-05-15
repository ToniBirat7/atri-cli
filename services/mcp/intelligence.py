# intelligence.py — code intelligence tools are in main.py
#
# The search_symbols, get_repo_map, and propose_plan tools were moved to main.py
# because the MCP orchestrator only loads services/mcp/main.py. Keeping them here
# meant they were never registered and would fail silently when called.
#
# See: services/mcp/main.py (search_symbols, get_repo_map, propose_plan sections)
