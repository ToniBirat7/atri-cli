# MCP Tools

**File:** `services/mcp/main.py`

The MCP (Model Context Protocol) server exposes tools to the agent loop. The `local-mcp` instance runs in-process with the orchestrator. There are **32 tools** total as of the last discovery refresh.

## Tool catalog

### Filesystem

| Tool | Key fields | Notes |
|------|-----------|-------|
| `list_directory` | `path` | Lists files/dirs at a path |
| `read_text_file` | `path` | Reads any file within project root |
| `write_file` | `path`, `content` | Creates or overwrites a file |
| `edit_file` | `path`, `exact_text_to_replace`, `replacement_text` | Exact-string patch; uses DiffEngine |
| `get_file_info` | **`target_path`** | Returns size, mtime, type. **Field is `target_path`, NOT `path`** — model sometimes confuses these |
| `directory_tree` | `path` | Recursive tree structure |
| `search_files` | `pattern`, `directory` | Find files by name pattern |

### Code search

| Tool | Key fields | Notes |
|------|-----------|-------|
| `grep_codebase` | `pattern`, `path?` | Regex search; skips .venv, node_modules, models, build |
| `get_repo_map` | none | High-level structural summary of the project |

### Shell

| Tool | Key fields | Notes |
|------|-----------|-------|
| `bash_exec` | `command`, `timeout?` | Runs shell commands; sandboxed with timeout |

### Version control

| Tool | Key fields | Notes |
|------|-----------|-------|
| `git_status` | none | Current git status |
| `git_log` | `n?` | Last N commits |
| `git_diff` | `ref?` | Diff against ref or working tree |

### Task management

| Tool | Key fields | Notes |
|------|-----------|-------|
| `todo_write` | `todos: List[str]` | Persists todos to `runtime/state/todos.json` |
| `todo_read` | none | Reads current todos |

### Intelligence / search

| Tool | Key fields | Notes |
|------|-----------|-------|
| `search_web` | `query` | Tavily web search (requires `TAVILY_API_KEY`) |
| `intelligence` tools | various | See `services/mcp/intelligence.py` |
| `search_adapter` tools | various | See `services/mcp/search_adapter.py` |

## Permission modes

When calling `/chat`, pass `permission_mode` in the request body:

| Mode | Behavior |
|------|---------|
| `default` | Prompts for dangerous operations |
| `bypassPermissions` | All tools execute without confirmation (used in E2E tests) |
| `acceptEdits` | Auto-accept file edits, prompt for bash |

`allowed_directory` restricts filesystem tools to a path prefix.

## Known schema gotchas

1. **`get_file_info`**: field must be `target_path`, not `path`. The model frequently hallucinates `path`. Causes `ValueError: Unexpected fields for tool 'get_file_info': path`.

2. **`edit_file`**: field is `exact_text_to_replace` (long name). The model sometimes shortens it. Check the schema via `GET /tools` if you get validation errors.

3. **`bash_exec`**: has a hard timeout enforced by the MCP server. Long-running commands (compilation, model load) will be killed. The LLM timeout (`LLM_TIMEOUT_SECONDS`) is separate.

## Related pages

- [[agent-loop]] — how tools are dispatched
- [[orchestrator]] — `/tools` and `/tools/refresh` endpoints
- [[known-issues]] — field name bugs
