---
description: Run a code review on recent changes
---

Review the current uncommitted changes. For each changed file:

1. Run `git diff` to see all unstaged changes
2. Run `git diff --cached` to see staged changes
3. For each changed file, check:
   - Bugs or logic errors
   - Missing error handling (especially for async functions and tool calls)
   - Security issues (path traversal, unsanitized input, secrets in code)
   - Performance concerns (N+1 queries, blocking I/O in async context)
   - Convention violations (wrong import style, wrong tool argument names like `path` instead of `target_file_path`)
4. Verify test coverage exists for changed orchestrator code
5. Check that any new env vars are documented in `.env.example`
6. Summarize findings grouped by severity: CRITICAL, WARNING, SUGGESTION
