# Codebase Analysis & Claude Code Initializer Prompt

> **Purpose:** Give this entire prompt to Google Antigravity (or any coding assistant) pointed at your project root. It will perform a deep codebase audit, then produce all the structured markdown files Claude Code needs to take over development with zero ramp-up.

---

## YOUR MISSION

You are a **Senior Codebase Analyst & Agentic Workflow Architect**. Your job has two phases:

### PHASE 1 — Deep Codebase Reconnaissance

Systematically explore this entire repository to build a complete mental model of the project. Do NOT skim. Do NOT assume. Read files, trace imports, inspect configs, follow data flows. You must understand every layer before writing a single output file.

### PHASE 2 — Generate Claude Code Initializer Files

Using your findings from Phase 1, produce a complete set of structured markdown files that will allow Claude Code to take over this project **without needing to scan the codebase itself**. These files become Claude Code's persistent memory and operating manual.

---

## PHASE 1: RECONNAISSANCE PROTOCOL

Execute each step below **in order**. For every step, record your findings internally before moving to the next. Be exhaustive.

### Step 1 — Project Identity & Purpose

- Read `README.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `LICENSE`, and any docs/ directory
- Identify: What does this project do? Who is it for? What problem does it solve?
- Determine the project's maturity stage: prototype / MVP / active development / maintenance / legacy
- Note the project name, version, description, and any stated goals or roadmap

### Step 2 — Tech Stack Inventory

Scan and catalog every technology in use:

- **Language(s) & version(s):** Check runtime configs (`.nvmrc`, `.python-version`, `.tool-versions`, `rust-toolchain.toml`, etc.)
- **Frameworks:** Read `package.json`, `Cargo.toml`, `pyproject.toml`, `go.mod`, `Gemfile`, `build.gradle`, `pom.xml`, `composer.json`, or equivalent
- **Package manager:** npm / yarn / pnpm / pip / poetry / cargo / go modules — check lockfiles to confirm
- **Database(s):** Look for ORM configs, migration files, schema files, connection strings in env templates
- **Infrastructure:** Docker files, docker-compose, Kubernetes manifests, Terraform, CDK, serverless configs
- **CI/CD:** `.github/workflows/`, `.gitlab-ci.yml`, `Jenkinsfile`, `.circleci/`, `bitbucket-pipelines.yml`
- **Testing:** Test runner configs (jest.config, vitest.config, pytest.ini, .rspec), test directories, coverage configs
- **Linting & Formatting:** ESLint, Prettier, Biome, Ruff, Black, Clippy, gofmt configs
- **Build system:** Webpack, Vite, Turbopack, esbuild, Rollup, Make, Bazel, or framework-native
- **External services / APIs:** Look for SDK imports, API client files, webhook handlers, third-party integrations

### Step 3 — Architecture & Folder Structure

Map the entire project layout:

- List every top-level directory and its purpose
- For each significant directory, go one or two levels deeper
- Identify architectural patterns: MVC, Clean Architecture, hexagonal, serverless, monolith, monorepo, micro-frontends, microservices
- Trace the **entry points**: Where does execution start? (main files, index files, server bootstrap, app entry)
- Map the **data flow**: Request → Route → Controller/Handler → Service/Business Logic → Data Layer → Response
- Identify **shared utilities**, common libraries, helper modules, and where they live
- Note any monorepo tooling (Turborepo, Nx, Lerna, workspaces configuration)

### Step 4 — Configuration & Environment

- Read ALL config files: `.env.example`, `.env.template`, `config/`, `settings/`
- Document every environment variable and what it controls
- Identify configuration patterns: Are configs hardcoded, env-driven, file-based, or remote?
- Check for feature flags, A/B testing configs, or conditional behavior switches
- Note any secrets management patterns (vault references, encrypted configs, secret templates)
- Check TypeScript config (`tsconfig.json`), Babel config, PostCSS config, or equivalent compiler/transpiler settings

### Step 5 — Data Layer & State Management

- Find all database schemas, migrations, seed files
- Identify ORMs/ODMs (Prisma, Drizzle, SQLAlchemy, TypeORM, Mongoose, ActiveRecord, GORM, Diesel, etc.)
- Map all data models / entities / tables and their relationships
- Check for caching layers (Redis, Memcached, in-memory)
- Identify state management on frontend (Redux, Zustand, MobX, Pinia, Vuex, Jotai, signals, etc.)
- Note any event systems, message queues, pub/sub, or async job processors

### Step 6 — API Layer & Routing

- Map every API endpoint: method, path, handler, middleware chain
- Identify authentication/authorization mechanisms (JWT, session, OAuth, API keys, RBAC/ABAC)
- Check for API documentation (Swagger/OpenAPI specs, GraphQL schema, tRPC routers)
- Note rate limiting, validation, error handling patterns
- Identify WebSocket, SSE, or real-time communication endpoints
- Check for API versioning strategy

### Step 7 — Frontend Architecture (if applicable)

- Identify component hierarchy and page structure
- Map routing configuration and navigation flow
- Check for design system / component library usage (shadcn/ui, MUI, Chakra, Ant Design, custom)
- Identify styling approach (CSS Modules, Tailwind, Styled Components, Emotion, SASS, vanilla CSS)
- Note any SSR/SSG/ISR configuration
- Check for internationalization (i18n) setup
- Identify form handling, validation libraries, and patterns

### Step 8 — Testing Landscape

- Inventory all test files and their types: unit, integration, e2e, snapshot, contract, load
- Note the exact commands to run each type of test
- Identify test utilities, fixtures, factories, mocks, and custom test helpers
- Check code coverage configuration and current coverage levels
- Note any testing patterns: TDD indicators, test-naming conventions, arrange-act-assert patterns
- Identify the command to run a single test file (this is critical for Claude Code)

### Step 9 — Build, Deploy & DevOps

- Document the exact build command and what it produces
- Map the deployment pipeline end to end
- Identify staging/production environment differences
- Check for infrastructure-as-code definitions
- Note any monitoring, logging, or observability setup (Sentry, DataDog, Prometheus, Grafana, etc.)
- Identify pre-commit hooks, husky configs, lint-staged

### Step 10 — Code Patterns, Conventions & Gotchas

- Identify naming conventions: files, functions, variables, components, tests
- Note import ordering conventions and module aliasing (path aliases like `@/`, `~/`)
- Check for code generation: scaffolding scripts, code generators, template files
- Identify error handling patterns: custom error classes, error boundaries, global handlers
- Look for **anti-patterns**, tech debt markers (`TODO`, `FIXME`, `HACK`, `XXX`), or known issues
- Note any **gotchas**: non-obvious behaviors, workarounds, legacy decisions that seem wrong but are intentional

### Step 11 — Progress Audit: What's Done vs. What's Left

- Compare the stated goals/roadmap (from README, issues, project boards) against actual implementation
- List all **completed features** with evidence (working routes, populated components, passing tests)
- List all **in-progress features** with evidence (partial implementations, TODOs, stub files, empty handlers)
- List all **planned/missing features** (referenced but not started, documented in issues/roadmap)
- Identify dead code, abandoned experiments, or deprecated modules
- Note any open bugs, known issues, or failing tests

### Step 12 — Dependency & Security Scan

- Check for outdated dependencies (look at lockfile dates, version ranges)
- Note any peer dependency warnings or resolution overrides
- Identify security-sensitive patterns: raw SQL, innerHTML, eval, unsanitized input
- Check for dependency audit results if available
- Note any vendored or forked dependencies

---

## PHASE 2: FILE GENERATION

Using ALL findings from Phase 1, generate the following files. Each file has a specific purpose and audience (Claude Code). Follow the format specifications exactly.

---

### FILE 1: `CLAUDE.md` (Root — The Most Important File)

**Purpose:** Claude Code reads this at the start of every session. It is the single source of persistent project context. Keep it concise and high-signal — under 150 lines. Every line must earn its place.

**Structure:**

```markdown
# [Project Name]

[One-sentence description of what this project is and does.]

## Tech Stack
[Language] [version] · [Framework] [version] · [Database] · [Key libraries]
Package manager: [exact manager and lockfile name]

## Commands
- `[command]`: [what it does] — e.g., `npm run dev`: Start dev server (port 3000)
- `[command]`: Run all tests
- `[command]`: Run a single test file — `[exact syntax with placeholder]`
- `[command]`: Lint and format
- `[command]`: Build for production
- `[command]`: Run database migrations
- `[command]`: [Any other critical commands]

## Architecture
- `/[dir]` — [purpose, 5-10 words max]
- `/[dir]` — [purpose]
- `/[dir]/[subdir]` — [purpose, only if non-obvious]
[Continue for all significant directories]

## Code Patterns
- [Pattern 1: e.g., "Use named exports, not default exports"]
- [Pattern 2: e.g., "Error handling uses custom AppError class in lib/errors.ts"]
- [Pattern 3: e.g., "All API routes validate with Zod schemas in [path]"]
- [Pattern 4: e.g., "Components follow: ComponentName/index.tsx + ComponentName.test.tsx"]
[Only include patterns Claude would get wrong without being told]

## Key Files
- `[path]`: [why it matters — e.g., "Main app entry, all middleware registered here"]
- `[path]`: [why it matters — e.g., "Database schema, source of truth for all models"]
- `[path]`: [why it matters — e.g., "Auth flow, JWT + refresh token logic"]
[5-15 files that are essential context for almost any task]

## Environment
- Copy `.env.example` to `.env` for local dev
- Required variables: [list critical ones with what they connect to]
- [Database name] runs on [port] — `[start command if applicable]`

## Gotchas
- [Non-obvious thing 1: e.g., "The /api/legacy/* routes use a different auth middleware — don't refactor without checking"]
- [Non-obvious thing 2: e.g., "Tests use an in-memory SQLite, NOT the Postgres schema — migration differences exist"]
- [Non-obvious thing 3: e.g., "The Image model stores URLs, not files. S3 upload happens in the upload service, not the model"]
[Only things Claude would likely get wrong]

## Current Status
**Completed:** [brief list of working features]
**In Progress:** [what's partially built]
**Not Started:** [what's planned but untouched]

## Compaction Rules
When compacting, always preserve: the full list of modified files, any failing test output, the current task objective, and all commands from the Commands section above.
```

**Rules for this file:**
- NO generic advice Claude already knows (like "write clean code")
- NO style rules a linter handles (use hooks instead)
- Every item must be something Claude cannot infer from reading code
- If Claude already does it correctly without the instruction, delete it

---

### FILE 2: `AGENTS.md` (Root — Cross-Agent Compatibility)

**Purpose:** Open standard read by Cursor, Codex, Windsurf, Zed, and other agents. Symlink to CLAUDE.md or make it a superset. This file ensures any coding agent can work on this project.

**Structure:**

```markdown
# [Project Name] — Agent Guide

## Project Overview
[2-3 sentences: what this is, who it's for, current state]

## Dev Environment Setup
- Prerequisites: [Node 20+, Python 3.12+, Docker, etc.]
- Install: `[exact install command]`
- Run: `[exact dev command]`
- Test: `[exact test command]`
- Build: `[exact build command]`

## Tech Stack
[Same as CLAUDE.md but can be slightly more verbose for agents that don't have the codebase indexed]

## Project Structure
[Same directory map as CLAUDE.md Architecture section]

## Code Conventions
- [Convention 1 with brief example if counterintuitive]
- [Convention 2]
[Focus on what agents get wrong — not what linters catch]

## Testing Instructions
- Unit tests: `[command]` — located in `[path pattern]`
- Integration tests: `[command]` — located in `[path pattern]`
- E2E tests: `[command]` — located in `[path pattern]`
- Run single test: `[exact syntax]`
- Tests must pass before any PR/commit

## Git Workflow
- Branch naming: `[convention, e.g., feat/*, fix/*, chore/*]`
- Commit style: `[conventional commits / other]`
- PR process: `[any required steps]`

## Boundaries
- ✅ **Safe to do:** Read files, run tests, run linter, format code
- ⚠️ **Ask first:** Install new dependencies, modify CI config, change DB schema
- 🚫 **Never do:** Commit secrets, delete migration files, modify production configs, push directly to main
```

---

### FILE 3: `.claude/rules/project-architecture.md`

**Purpose:** Lazy-loaded rule file that provides deep architectural context. Loaded when Claude touches architectural files.

**Structure:**

```markdown
---
paths:
  - "src/**"
  - "app/**"
  - "lib/**"
  - "server/**"
---

# Architecture Rules

## Data Flow
[Request lifecycle: entry point → middleware → handler → service → data layer → response]
[Draw the flow with arrows using text]

## Module Boundaries
- [Module A] should never import from [Module B] directly — use [shared interface]
- [Data layer] is the only module that talks to the database
- [Service layer] contains all business logic — controllers are thin

## Dependency Direction
[Describe which layers can depend on which — e.g., "handlers → services → repositories → models, never the reverse"]

## Adding New Features Checklist
1. [Step 1: e.g., "Add Zod schema in schemas/"]
2. [Step 2: e.g., "Create service function in services/"]
3. [Step 3: e.g., "Add route handler in routes/"]
4. [Step 4: e.g., "Write tests in __tests__/"]
5. [Step 5: e.g., "Update OpenAPI spec if it's a new endpoint"]
```

---

### FILE 4: `.claude/rules/database.md`

**Purpose:** Loaded when Claude touches database-related files.

```markdown
---
paths:
  - "prisma/**"
  - "drizzle/**"
  - "migrations/**"
  - "src/models/**"
  - "src/db/**"
  - "**/schema.*"
  - "**/migration*"
---

# Database Rules

## ORM
[ORM name and version] — schema defined in `[path]`

## Models & Relationships
[List every model/table with key fields and relationships in natural language]
[e.g., "User has many Posts. Post belongs to User and has many Comments. Comment belongs to Post and User."]

## Migration Workflow
1. Modify schema in `[path]`
2. Generate migration: `[command]`
3. Apply migration: `[command]`
4. NEVER manually edit migration files after generation

## Query Patterns
- [Pattern: e.g., "Always use select() to limit fields returned — never select *"]
- [Pattern: e.g., "Use transactions for multi-table writes via db.transaction()"]
- [Pattern: e.g., "Pagination uses cursor-based approach, not offset"]

## Seed Data
- Seed command: `[command]`
- Seed file location: `[path]`
```

---

### FILE 5: `.claude/rules/testing.md`

**Purpose:** Loaded when Claude creates or modifies test files.

```markdown
---
paths:
  - "**/*.test.*"
  - "**/*.spec.*"
  - "**/__tests__/**"
  - "**/test/**"
  - "**/tests/**"
  - "**/*.cy.*"
  - "**/e2e/**"
  - "**/fixtures/**"
---

# Testing Rules

## Test Runner
[Runner name]: config at `[path]`

## Running Tests
- All tests: `[command]`
- Single file: `[exact command with placeholder, e.g., npx vitest run path/to/file.test.ts]`
- Watch mode: `[command]`
- Coverage: `[command]`

## Test Structure
- File naming: `[pattern, e.g., ComponentName.test.tsx alongside ComponentName.tsx]`
- Test naming: `[pattern, e.g., "should [expected behavior] when [condition]"]`
- Arrange-Act-Assert structure preferred

## Test Utilities
- Custom helpers in `[path]`: [what they do]
- Mock factories in `[path]`: [what they do]
- Test database setup: `[how it works]`

## What to Test
- Every new API endpoint needs: [request validation test, happy path, error cases, auth check]
- Every new component needs: [renders correctly, handles user interaction, handles loading/error states]
- Every new utility function needs: [happy path, edge cases, error handling]
```

---

### FILE 6: `.claude/rules/frontend.md` (if applicable)

**Purpose:** Loaded when Claude touches frontend files.

```markdown
---
paths:
  - "src/components/**"
  - "src/app/**"
  - "src/pages/**"
  - "app/**/*.tsx"
  - "app/**/*.jsx"
  - "components/**"
---

# Frontend Rules

## Component Patterns
- Component structure: `[describe the canonical pattern with file names]`
- Styling approach: `[Tailwind / CSS Modules / etc. with any conventions]`
- State management: `[library and patterns]`

## Routing
- Router: `[Next.js App Router / React Router / etc.]`
- Route files live in: `[path]`
- Dynamic routes pattern: `[describe]`

## Data Fetching
- [Pattern: e.g., "Server components fetch data directly. Client components use React Query."]
- API client location: `[path]`
- [Any caching/revalidation strategy]

## UI Library
- Using: `[shadcn/ui / MUI / custom]`
- Component imports from: `[path]`
- [Any customization notes]
```

---

### FILE 7: `.claude/commands/review.md` (Slash Command)

```markdown
---
description: Run a code review on recent changes
---

Review the current uncommitted changes. For each changed file:

1. Read the diff with `git diff`
2. Check for: bugs, missing error handling, security issues, performance concerns, convention violations
3. Verify test coverage exists for the changes
4. Summarize findings grouped by severity: CRITICAL, WARNING, SUGGESTION
```

---

### FILE 8: `.claude/commands/implement-feature.md` (Slash Command)

```markdown
---
description: Implement a feature following project conventions
---

Implement the feature described by the user. Follow this workflow:

1. **Understand:** Read the requirement. Ask clarifying questions ONLY if the request is genuinely ambiguous.
2. **Plan:** List the files you'll create or modify. Identify which existing patterns to follow by reading a similar, already-implemented feature.
3. **Implement:** Write the code following project conventions from CLAUDE.md and .claude/rules/.
4. **Test:** Write tests for the new code. Run: `$TEST_COMMAND_SINGLE_FILE`
5. **Verify:** Run the linter: `$LINT_COMMAND`. Fix any issues.
6. **Report:** Summarize what was done, files changed, and any decisions made.

If a similar feature already exists, read its implementation first and follow the same patterns exactly.
```

---

### FILE 9: `.claude/commands/status.md` (Slash Command)

```markdown
---
description: Show project completion status and next steps
---

Analyze the current project state:

1. Run `git log --oneline -20` to see recent work
2. Check for any failing tests: `$TEST_COMMAND`
3. Check for lint errors: `$LINT_COMMAND`
4. Review TODO/FIXME comments: `grep -rn "TODO\|FIXME\|HACK\|XXX" --include="*.ts" --include="*.tsx" --include="*.py" --include="*.js" --include="*.jsx" src/`
5. Compare implemented features against the "Current Status" section in CLAUDE.md
6. Report: what's working, what's broken, what's next
```

---

### FILE 10: `.claude/skills/codebase-navigator/SKILL.md`

```markdown
---
name: codebase-navigator
description: Use when you need to understand how a feature is implemented or find where specific logic lives. Triggers on questions like "where is X handled", "how does Y work", "find the code that does Z".
---

# Codebase Navigator

When asked to find or understand existing code:

1. Start with the relevant entry point from this map:
   - API routes: `[path]`
   - Components: `[path]`
   - Business logic: `[path]`
   - Data models: `[path]`
   - Utilities: `[path]`
   - Config: `[path]`

2. Use grep/find to locate the specific code:
   - `grep -rn "[search term]" --include="*.[ext]" [directory]`
   - `find [directory] -name "*[pattern]*" -type f`

3. Trace the full chain: entry point → handler → service → data layer

4. Report your findings with file paths and line numbers so the user can verify.

Never guess. Always read the actual code.
```

---

### FILE 11: `docs/PROJECT-STATUS.md` (Living Document)

**Purpose:** Detailed project status that Claude can reference and update. More verbose than the CLAUDE.md status section.

```markdown
# Project Status — [Date Generated]

## Feature Inventory

### ✅ Completed
| Feature | Key Files | Tests | Notes |
|---------|-----------|-------|-------|
| [Feature 1] | `[file paths]` | ✅ `[test file]` | [any notes] |
| [Feature 2] | `[file paths]` | ✅ `[test file]` | [any notes] |

### 🚧 In Progress
| Feature | Key Files | Status | Blocking Issues |
|---------|-----------|--------|-----------------|
| [Feature 3] | `[file paths]` | [e.g., "API done, frontend pending"] | [any blockers] |

### 📋 Not Started
| Feature | Priority | Dependencies | Notes |
|---------|----------|--------------|-------|
| [Feature 4] | [High/Med/Low] | [depends on Feature X] | [any context] |

## Known Issues
- [ ] [Issue 1: description + file location]
- [ ] [Issue 2: description + file location]

## Tech Debt
- [ ] [Debt 1: what and where]
- [ ] [Debt 2: what and where]

## Dependency Notes
- [Any outdated, deprecated, or problematic dependencies]
```

---

### FILE 12: `.claude/settings.json` (Template)

**Purpose:** Permissions and hook configuration.

```json
{
  "permissions": {
    "allow": [
      "Read",
      "Grep",
      "Glob",
      "Bash(npm run test*)",
      "Bash(npm run lint*)",
      "Bash(npm run build*)",
      "Bash(npx prettier*)",
      "Bash(git diff*)",
      "Bash(git log*)",
      "Bash(git status)"
    ],
    "deny": [
      "Bash(rm -rf *)",
      "Bash(git push*)",
      "Bash(npm publish*)",
      "Bash(*SECRET*)",
      "Bash(*PASSWORD*)",
      "Bash(*API_KEY*)"
    ]
  }
}
```

*Adjust commands to match the project's actual package manager and scripts.*

---

## OUTPUT REQUIREMENTS

1. **Generate ALL files listed above** — adapt each to the actual project findings
2. **Skip files that don't apply** — e.g., skip `frontend.md` if there's no frontend
3. **Add extra rules files** if the project has domains not covered above (e.g., `auth.md`, `payments.md`, `ml-pipeline.md`)
4. **Use actual paths, commands, and patterns** from the codebase — NO placeholders in the final output
5. **Replace all `$VARIABLES`** with the real commands discovered in Phase 1
6. **Keep CLAUDE.md under 150 lines** — ruthlessly prune. Move details to rules files
7. **Every instruction must fail the "Would Claude do this anyway?" test** — if yes, delete it
8. **Prefer examples over explanations** — one code snippet beats three paragraphs

---

## CRITICAL PRINCIPLES

- **Write for the machine, not the human.** These files are consumed by Claude Code at the start of each session. Clarity and precision beat prose.
- **Less is more.** Every token in CLAUDE.md competes with the actual task. A 300-line CLAUDE.md degrades performance. A 80-line one that's all signal is optimal.
- **Document what's surprising, not what's obvious.** Claude can read code. It can't read your mind about why a weird pattern exists.
- **Commands are king.** The exact `test`, `lint`, `build`, and `dev` commands are the highest-value lines in CLAUDE.md.
- **Progressive disclosure.** CLAUDE.md is always loaded. Rules files load on file-match. Skills load on-demand. Layer information accordingly.
- **Symlink AGENTS.md → CLAUDE.md** if the content is identical, so all agent tools benefit.

---

## VERIFICATION CHECKLIST

Before delivering the files, verify:

- [ ] Every command in CLAUDE.md is copy-pasteable and correct
- [ ] Every file path referenced actually exists in the project
- [ ] No placeholder text remains (no `[brackets]`, no `$VARIABLES`)
- [ ] CLAUDE.md is under 150 lines
- [ ] Rules files have correct `paths:` frontmatter YAML
- [ ] Gotchas section only contains things Claude would actually get wrong
- [ ] Status section reflects the real state of the project right now
- [ ] Settings.json commands match the project's actual package manager
