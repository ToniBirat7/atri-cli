# Wiki Schema (CLAUDE.md equivalent)

This document tells the LLM how to maintain the Atri Code wiki. Read this before any ingest, query, or lint operation.

---

## Directory structure

```
.wiki/
  SCHEMA.md          ← this file; wiki conventions
  index.md           ← catalog of all pages (LLM updates on every ingest)
  log.md             ← append-only event log (LLM appends on every operation)
  overview.md        ← project summary
  architecture.md    ← system diagram + module map
  agent-loop.md      ← ReAct loop internals
  mcp-tools.md       ← tool catalog + schemas
  orchestrator.md    ← FastAPI routes + lifecycle
  llm-inference.md   ← llama-server flags + hardware
  cli.md             ← atri CLI + TUI commands
  configuration.md   ← all .env variables
  auth.md            ← auth modes + permissions
  prompt-policy.md   ← profiles + thinking mode
  e2e-test-results.md← live test results
  known-issues.md    ← bugs, gotchas, workarounds
```

---

## Page format

Every page uses plain GitHub-flavored markdown. No frontmatter required.

- **H1** (`#`) — page title
- **H2** (`##`) — major sections
- **H3** (`###`) — subsections
- Tables, code blocks, and bullet lists freely used
- Cross-references: `[[page-name]]` (without `.md`) — link to another wiki page

---

## Ingest workflow

When a new source is added:

1. Read the source
2. Discuss key takeaways with the user (optional but recommended)
3. Write or update the relevant concept pages
4. Update `index.md` if new pages were created
5. Append to `log.md` with date, source name, and pages touched

---

## Query workflow

When the user asks a question:

1. Read `index.md` to identify relevant pages
2. Read those pages
3. Answer with citations to page names
4. If the answer surfaces new knowledge worth keeping, file it as a new page or update section

---

## Lint checklist

Run periodically to keep the wiki healthy:
- [ ] Pages referenced by `[[link]]` that don't exist → create stubs
- [ ] Stale facts (e.g., `.env` values that may have changed) → re-read source, update
- [ ] Orphan pages (no inbound links) → add links or merge
- [ ] `index.md` missing new pages → add entries
- [ ] `known-issues.md` with `Status: Fixed` entries older than 30 days → archive

---

## Conventions

- The LLM writes the wiki; the human reads it
- Never delete a `known-issues.md` entry — update its status instead
- `log.md` is append-only — never edit past entries
- `e2e-test-results.md` is updated after each test run
- When `.env` values change, update both `configuration.md` and the **Current live values** section
