# MCP Service

This directory contains the FastMCP server(s) used by Tarbar_AI.

Current server entrypoint:
- `main.py`

## Filesystem MCP Server (Production-Grade)

The server now exposes a hardened local filesystem toolset similar to Claude Desktop filesystem MCP behavior.

### Security Model

- Strict allow-list sandbox: access is limited to configured directories only.
- Path traversal prevention: normalized real paths must remain inside allowed roots.
- Hidden files blocked by default.
- Read/write/search size and result limits.
- Destructive actions require explicit flags (for example, recursive delete).

### Configuration

Set environment variables before launching:

- `MCP_ALLOWED_DIRS`: os.pathsep-separated allowed directories.
 - Linux/macOS example: `/home/user/project:/home/user/docs`
 - Windows example: `C:\\project;D:\\docs`
- `MCP_MAX_READ_BYTES` (default: `1048576`)
- `MCP_MAX_WRITE_BYTES` (default: `1048576`)
- `MCP_MAX_SEARCH_RESULTS` (default: `200`)
- `MCP_MAX_WEB_SEARCH_RESULTS` (default: `8`)
- `MCP_MAX_FETCH_CHARS` (default: `12000`)
- `BRAVE_SEARCH_API_KEY` (optional, enables Brave provider)
- `MCP_ALLOW_HIDDEN` (default: `false`)
- `MCP_LOG_LEVEL` (default: `INFO`)

If `MCP_ALLOWED_DIRS` is not set, the server defaults to the repository root.

### Frontend-driven Directory Selection

The frontend can send a user-selected directory with each chat request. The orchestrator applies it by calling:

- `set_allowed_directory(path)`

This updates the active filesystem sandbox at runtime, similar to the Claude Desktop pattern where user-selected roots define tool access boundaries.

### Tools

Read-only tools:
- `list_allowed_directories`
- `list_directory`
- `directory_tree`
- `read_text_file`
- `read_multiple_files`
- `read_media_file_base64`
- `get_file_info`
- `search_files`
- `search_web`
- `fetch_url`
- `server_status`

Write/destructive tools:
- `create_directory`
- `write_file`
- `append_file`
- `edit_file`
- `move_file`
- `delete_path`
- `write_json_file`

### Run

From this directory:

`fastmcp run main.py:mcp`

Or from repo root via Makefile target:

`make mcp`
