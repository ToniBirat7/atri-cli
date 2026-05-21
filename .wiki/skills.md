# Skills

The skills system lets users define reusable slash commands that the agent can invoke by name. Skills are Markdown files with a structured header that describe a task, set a system prompt, and optionally pre-load context.

---

## Overview

Skills are discovered from two locations (in order of priority):

1. **Project-local:** `.atri/skills/` in the current working directory
2. **User-global:** `~/.atri/skills/`

Each skill is a `.md` file. The filename (without extension) becomes the slash command name.

---

## Invocation

In the TUI, type `/` followed by the skill name:

```
/refactor-auth
/generate-tests
/explain-code
```

The agent can also invoke skills autonomously when the task matches a known skill. Skills listed by `/skills` appear as available commands.

Skills can also be invoked from the CLI:

```bash
atri --prompt "/refactor-auth Fix the JWT middleware"
```

---

## SKILL.md format specification

A skill file must begin with a YAML front-matter block delimited by `---`, followed by the skill body in Markdown.

```markdown
---
name: refactor-auth
description: Refactor authentication middleware to use bcrypt and JWT best practices
version: 1.0
author: yourname
tags: [refactor, auth, security]
model: default          # optional: route to specific model
permission_mode: default  # default | bypassPermissions | acceptEdits
allowed_tools:          # optional: restrict which MCP tools are available
  - read_text_file
  - edit_file
  - grep_codebase
context_files:          # optional: pre-load these files into context
  - services/orchestrator/auth.py
  - services/orchestrator/config.py
---

## Skill: Refactor Auth

You are an expert Python security engineer. When asked to refactor authentication code:

1. Identify all password hashing — replace MD5/SHA1/plain with bcrypt.
2. Validate JWT signing — ensure `HS256` with a secret from env, never hardcoded.
3. Check for timing-safe comparisons (`hmac.compare_digest`).
4. Update tests to cover the new implementation.
5. Do not change the public API surface.

Always show a summary of changes before editing files.
```

### Front-matter fields

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `name` | Yes | string | Skill identifier (must match filename without `.md`) |
| `description` | Yes | string | Short description shown in `/skills` listing |
| `version` | No | string | Semver version for tracking |
| `author` | No | string | Author/source identifier |
| `tags` | No | list | Categorization tags |
| `model` | No | string | Model routing key (`default`, `fast`, or a model ID) |
| `permission_mode` | No | string | `default`, `bypassPermissions`, or `acceptEdits` |
| `allowed_tools` | No | list | Restrict MCP tools available during skill execution |
| `context_files` | No | list | Paths to pre-load into the system prompt as context |

### Skill body

The body is a Markdown system prompt that guides agent behavior during the skill session. It may include:

- Persona / role definition
- Step-by-step instructions
- Constraints (what NOT to do)
- Output format expectations
- Examples

---

## Discovery locations

```
~/.atri/skills/          User-global skills (available in all projects)
.atri/skills/            Project-local skills (override user-global if same name)
```

Skills are loaded at startup. To add a new skill without restarting, use `/skills reload` (if available) or restart the TUI.

### Auto-generated skills (memory mining)

After sessions with 10+ turns complete, the memory service (`memory_service.py`) analyzes the session and may generate auto-skills saved to `~/.atri/skills/`. These have `source: auto` in their metadata and are shown with an `[auto]` tag in `/skills`. They are never applied automatically — user review and acceptance is required.

---

## Example skill files

### `~/.atri/skills/explain-code.md`

```markdown
---
name: explain-code
description: Explain selected code in plain language with complexity analysis
version: 1.0
tags: [explain, learning]
---

You are a patient, expert software educator. When given code:

1. Explain what it does in plain language (no jargon).
2. Identify the algorithm and its time/space complexity.
3. Point out any non-obvious gotchas or edge cases.
4. Suggest a simpler alternative if one exists.

Keep explanations concise. Use code snippets to illustrate points.
```

### `.atri/skills/generate-tests.md`

```markdown
---
name: generate-tests
description: Generate pytest tests for a given module
version: 1.0
tags: [testing, pytest]
permission_mode: acceptEdits
allowed_tools:
  - read_text_file
  - write_file
  - grep_codebase
  - bash_exec
context_files:
  - services/orchestrator/tests/
---

You are an expert Python test engineer specializing in pytest.

When asked to generate tests for a module:
1. Read the module with read_text_file.
2. Identify all public functions and classes.
3. Write pytest tests covering: happy path, edge cases, error cases.
4. Use fixtures for shared state. Mock external dependencies with `unittest.mock`.
5. Write tests to `services/orchestrator/tests/test_<module_name>.py`.
6. Run the tests with bash_exec and report results.

Follow the existing test style in the context files.
```

---

## Listing and managing skills

In the TUI:

```
/skills          List all available skills (name, description, source)
/skills reload   Reload skill files from disk
```

From the CLI:

```bash
atri --prompt "/skills"
```

---

## Related pages

- [[tui]] — slash commands and TUI interaction
- [[agent-loop]] — how skills modify the system prompt
- [[configuration]] — model routing config
