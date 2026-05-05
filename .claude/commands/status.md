---
description: Show project completion status and next steps
---

Analyze the current project state:

1. Run `git log --oneline -20` to see recent work
2. Run `git status` to see uncommitted changes
3. Check for failing tests: `cd services/orchestrator && .venv/bin/python -m pytest tests/ -v 2>&1 || echo "No tests yet"`
4. Check service health: `curl -s http://127.0.0.1:8001/health | python3 -m json.tool 2>/dev/null || echo "Orchestrator not running"`
5. Review TODO/FIXME comments in project code (excluding llama.cpp submodule):
   `grep -rn "TODO\|FIXME\|HACK" --include="*.py" --include="*.ts" --include="*.tsx" services/ apps/cli/ apps/frontend/src/`
6. Check current branch and compare against CLAUDE.md "Current Status" section
7. Report:
   - **What's working:** confirmed via git log and test results
   - **What's broken or incomplete:** failing tests, TODOs, stubs
   - **Recommended next action:** single highest-value thing to do next
