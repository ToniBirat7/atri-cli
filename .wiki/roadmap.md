# Atri-CLI v3 Roadmap

*Research-driven feature roadmap based on deep analysis of Pi (earendil-works/pi) and Gemini CLI (google-gemini/gemini-cli). Updated: 2026-05-20.*

---

## Research Sources

| Project | URL | Stars | Language |
|---------|-----|-------|----------|
| Pi Agentic Harness | https://github.com/earendil-works/pi | 51.9k | TypeScript |
| Gemini CLI | https://github.com/google-gemini/gemini-cli | — | TypeScript |

---

## Key Learnings

### From Pi

- **Primitives-first**: Only 4 core tools (read, write, edit, bash). Everything else is an extension. Avoids bloat.
- **Tree-structured sessions**: Append-only JSONL per session; each entry has UUID + parent pointer. Enables non-destructive `/fork` and `/tree` navigation without losing history.
- **Compaction pipeline**: Auto-compact at 80% token limit. Summarize oldest turns, re-attach 5 recently-read files. Branch-aware.
- **Skills system**: Named dirs with `SKILL.md` (YAML frontmatter + body). Only description in initial prompt; full body loaded on invocation → keeps token usage flat with many skills.
- **MCP proxy mode**: Single ~200-token proxy tool replaces all N tool schemas, reducing prompt overhead dramatically.
- **Differential TUI rendering**: CSI 2026 synchronized output; only changed lines are sent. Eliminates flicker during streaming.
- **Hash-anchored editing**: Each line tagged with stable 2-letter BPE bigram hash → edits survive small code shifts better than line numbers.
- **Monitor/file watch mode**: Inotify-based; agent woken on file change with event history.
- **Progressive tool streaming**: Partial tool arguments displayed in TUI before call completes → reduces perceived latency.

### From Gemini CLI

- **Event-driven agent loop**: Typed event lifecycle (`agent_start/end`, `turn_start/end`, `tool_execution_start/end`, `thinking_start/end`). Supports checkpoint + replay by eventId.
- **PLAN mode**: Read-only exploration — only file reads + web search; writes blocked; routes to higher-reasoning model for planning, faster model for execution.
- **Hook system**: `beforeToolCall` / `afterToolCall` hooks. Enables validation, path protection, caching, approval gates without changing core loop.
- **Confirmation bus**: Message-based approval — tool emits approval request, UI responds, core executes or cancels.
- **PTY-based bash**: Full pseudo-terminal with 300K scrollback, binary detection, background process tracking.
- **Context compression**: Conversation summarization + token truncation + tool distillation (verbose output masking) + selective history injection.
- **Auto memory**: Background mining of sessions with 10+ turns; skill extraction → candidate review → `/memory inbox`.
- **Model routing**: Strategy pattern — different models for PLAN (high-context) vs quick responses (fast small model) vs code editing (default).
- **Sandbox**: `ResolvedSandboxPaths` with filesystem permission levels; governance file protection (`.git`, `.env*`, `.gitignore` write-protected).
- **Multiple MCP servers**: Per-server auth providers (OAuth, API key, Bearer), namespaced tool routing.

---

## Phased Implementation Plan

### Phase 1 — Foundation Fixes (Week 1-2)

| Item | File | Description |
|------|------|-------------|
| 1.1 Auto-compaction | `agent_loop.py`, new `compaction.py` | Detect 80% ctx usage → summarize oldest turns → re-attach recent files |
| 1.2 Fix max_turns bug | `agent_loop.py` | Per-request override must work; pre-turn budget check |
| 1.3 Fix MCP field aliases | `services/mcp/main.py` | Add `path` alias for `target_path`/`target_file_path` |
| 1.4 Hook system | new `hooks.py` | `beforeToolCall` / `afterToolCall` registry wired into agent loop |

### Phase 2 — Session Architecture (Week 2-3)

| Item | File | Description |
|------|------|-------------|
| 2.1 Tree-structured sessions | new `session_tree.py` | Append-only JSONL, UUID+parent, O(1) lookup |
| 2.2 Fork & branch | `session_tree.py`, `main.py` | `/fork`, `/tree` commands; `atri resume <id>` |
| 2.3 Event checkpointing | `agent_loop.py` | Write typed events to JSONL as fired; resume-from-eventId |

### Phase 3 — TUI & UX Overhaul (Week 3-4)

| Item | File | Description |
|------|------|-------------|
| 3.1 Differential rendering | new `renderer.py` | 3-strategy render; changed-lines-only ANSI update |
| 3.2 PLAN mode | `main.py`, `prompt_policy.py` | `/plan`→read-only; `/implement`→execute; status bar indicator |
| 3.3 PTY bash | `services/mcp/main.py` | `pty.openpty()`, 10K scrollback, streaming, binary detect |
| 3.4 Inline diff viewer | new `diff_renderer.py` | Color-coded unified diff inline before approve/reject |
| 3.5 New slash commands | `main.py` | `/fork`, `/tree`, `/plan`, `/implement`, `/mcp`, `/compact`, `/model`, `/skills` |

### Phase 4 — Tools & Intelligence (Week 4-5)

| Item | File | Description |
|------|------|-------------|
| 4.1 Tree-sitter search | `services/mcp/main.py` | Complete `search_symbols`; Python/TS/JS/Go/Rust |
| 4.2 File watch / monitor | new `services/mcp/monitor.py` | inotify + polling; agent woken on trigger |
| 4.3 MCP proxy mode | `mcp_orchestrator.py` | Single proxy tool; on-demand tool resolution |
| 4.4 External MCP servers | `mcp_orchestrator.py` | `MCP_SERVERS` config; auth providers; namespaced dispatch |
| 4.5 Tool result caching | `agent_loop.py` | LRU cache keyed on (tool, args_hash); file mtime invalidation |
| 4.6 Safe bash (bubblewrap) | `services/mcp/main.py` | `bash_exec_safe` via `bwrap`; allow/deny path lists |

### Phase 5 — Advanced Features (Week 5-6)

| Item | File | Description |
|------|------|-------------|
| 5.1 Skills system | new `skills_loader.py` | `SKILL.md` in `.atri/skills/`; progressive disclosure; `/skills` command |
| 5.2 Multi-model + routing | new `model_router.py` | Detect all GGUF models; strategy routing by task type; `/model` command |
| 5.3 Governance file protection | `hooks.py` + `main.py` | Block writes to `.git/`, `.env*`, `.ssh/` via beforeToolCall hook |
| 5.4 Auto memory mining | new `memory_service.py` | Background skill extraction from 10+ turn sessions; candidate review |
| 5.5 Context distillation | `agent_loop.py` | Results >2KB → 2KB preview + disk; `read_tool_result(id)` tool |

---

## Priority Order (if time-constrained)

1. Phase 1 — bug fixes + hooks (unblocks everything)
2. Phase 3.3 — PTY bash (biggest UX gap)
3. Phase 1.1 — auto-compaction (critical for long sessions)
4. Phase 2 — session tree (fork/resume)
5. Phase 4.1 — Tree-sitter semantic search
6. Phase 3.2 — PLAN mode
7. Phase 5.1 — skills system
8. Remainder of Phase 4 + 5

---

## Comparison Matrix

| Feature | atri-cli now | Pi | Gemini CLI | Claude Code |
|---------|-------------|-----|------------|-------------|
| Context auto-compaction | ❌ | ✅ | ✅ | ✅ |
| Session tree/forking | ❌ | ✅ | partial | ❌ |
| Hook system | ❌ | ✅ | ✅ | ❌ |
| PTY bash | ❌ | ✅ | ✅ | ✅ |
| PLAN mode | ❌ | via ext | ✅ | ✅ |
| Inline diff viewer | partial | ✅ | ✅ | ✅ |
| Differential TUI render | ❌ | ✅ | partial | N/A |
| Skills system | ❌ | ✅ | via skills | ❌ |
| Multiple MCP servers | ❌ | ✅ | ✅ | ✅ |
| MCP proxy mode | ❌ | ✅ | ❌ | ❌ |
| Tree-sitter search | stub | via ext | ❌ | ✅ |
| File watching | ❌ | ✅ | ❌ | ✅ |
| Model routing | ❌ | ❌ | ✅ | ✅ |
| Auto memory mining | ❌ | via ext | ✅ (exp) | ✅ |
| Safe bash sandboxing | ❌ | via ext | ✅ | ✅ |
| Tool result caching | ❌ | ❌ | ❌ | ✅ |
| Governance file protection | ❌ | via ext | ✅ | ✅ |
