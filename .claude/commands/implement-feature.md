---
description: Implement a feature following project conventions
---

Implement the feature described by the user. Follow this workflow:

1. **Understand:** Read the requirement. If it's an orchestrator feature, read `services/orchestrator/api.py` L1-100 first to understand the pattern. If it's a tool, read `services/mcp/main.py` L1-100.

2. **Find a parallel:** Before writing any code, identify an existing similar feature and read its full implementation. For example, if adding a new API endpoint, read an existing one (e.g. `/conversations` route in `api.py`).

3. **Plan:** List the exact files you'll create or modify.

4. **Implement:** Follow these conventions:
   - Orchestrator modules: include dual import blocks (try relative, except absolute)
   - MCP tools: use `@mcp.tool()`, always call `_resolve_path()` for filesystem ops
   - API endpoints: add Pydantic models, call `_authenticate_request()`, emit `_log_event()`
   - Frontend components: PascalCase, named export, inline TypeScript props, TailwindCSS only

5. **Test:** Run `cd services/orchestrator && .venv/bin/python -m pytest tests/ -v`. If test file doesn't exist yet, write tests for the new feature.

6. **Verify:** Check `make health` confirms services are still healthy after code changes.

7. **Report:** Summarize files changed, decisions made, and any follow-up tasks.
