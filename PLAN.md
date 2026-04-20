Grand Plan: Atri Code Production Program
Duration: 6 weeks, staged, with acceptance gates.

Phase 0 (Hotfix Reliability, 2-3 days)

Make MCP startup fail-fast if required server init fails.
Add explicit readiness gate: local-mcp initialized plus required tools discovered.
Bootstrap should block until readiness endpoint confirms tool registry health.
Add atri-cli doctor command for first-run diagnostics.
Acceptance:
No silent "healthy but broken tools" state.
Fresh install + first prompt succeeds end-to-end in one run.

Phase 1 (Rebrand and Command Migration, 3-4 days)

Rename product surface to Atri Code across CLI banners and docs.
Install primary command as atri-cli.
Keep tarbar as compatibility alias for one release cycle.
Keep claude alias behavior safe and non-destructive.
Acceptance:
atri-cli is canonical.
Old command still works temporarily with deprecation notice.

Phase 2 (Interactive Input Engine, 1 week)

Replace raw input() with prompt_toolkit-based shell layer.
Implement slash command registry with filtering and tab completion.
Add command help descriptions inline as user types slash prefix.
Add command history search and multiline compose parity.
Acceptance:
Slash autocomplete works for /mode, /help, /timeline, etc.
Keyboard UX is stable on Linux/macOS terminals.

Phase 3 (Beautiful Fullscreen TUI, 1.5 weeks)

Add fullscreen renderer mode similar to modern coding CLIs.
Persistent panes: conversation, status, task list, tool events.
Animated but accessible progress states with reduced-motion mode.
Keep fallback non-fullscreen mode for compatibility.
Acceptance:
Rich TUI defaults on supported terminals.
Fallback mode remains functional and stable.

Phase 4 (Pipeline Robustness and MCP Hardening, 1 week)

Deterministic MCP server lifecycle with retries and clear error taxonomy.
Tool discovery caching with explicit refresh controls.
Startup trace summary: what initialized, what failed, recommended fix.
Enforce required tools before first prompt acceptance.
Acceptance:
No local-mcp not initialized error in normal flow.
Failed states produce actionable guidance.

Phase 5 (Production Hygiene and Security, 1 week)

Remove hardcoded keys and move to secure env/config model.
Add secret scanning and pre-commit protections.
Add cleanup command: atri-cli cleanup with safe modes.
Add policy docs and release checklist enforcement in CI.
Acceptance:
No secrets in tracked code.
Runtime junk is auto-cleanable and never tracked.

Phase 6 (Release Readiness, 1 week)

Build matrix tests: fresh install, first run, restart, recovery.
E2E tests for MCP readiness, slash commands, and TUI smoke checks.
Package options: script installer plus bundled binary channel.
Release candidate and rollback plan.
Acceptance:
One-command install, one-command start, consistent first prompt success.
Production release checklist fully green.

Detailed Task Timeline (Week-by-Week)

Week 1

Day 1: MCP fail-fast and readiness model.
Day 2: Bootstrap blocks on full readiness.
Day 3: doctor command and startup diagnostics.
Day 4-5: rebrand groundwork (Atri Code, atri-cli) with compatibility shims.
Week 2

Day 1-2: prompt_toolkit integration.
Day 3: slash command registry and completion engine.
Day 4: history/search and multiline input.
Day 5: cross-shell validation.
Week 3

Day 1-2: fullscreen TUI architecture.
Day 3-4: panes, task/status events, animations.
Day 5: reduced-motion and accessibility switches.
Week 4

Day 1-2: MCP lifecycle robustness.
Day 3: discovery/refresh reliability.
Day 4-5: orchestrator and CLI error contracts.
Week 5

Day 1: remove hardcoded secrets and rotate keys.
Day 2: cleanup command and retention policies.
Day 3-4: CI production hygiene gates.
Day 5: docs hardening for master and web.
Week 6

Day 1-2: fresh-install E2E suite.
Day 3: packaged distribution smoke tests.
Day 4: release candidate.
Day 5: go/no-go and production release.
What We Should Do Immediately Next

Current status snapshot:
- Phase 0 completed.
- Phase 1 completed.
- Phase 2 completed.
- Phase 3 completed.
- Phase 4 completed (lifecycle, cache hardening, reconnect/error contracts, startup summary).
- Phase 5 completed (secret hygiene, cleanup command, pre-commit/CI policy gates, release checklist docs).
- Phase 6 in progress (release-readiness workflow, scenario matrix runner, package channel builder, rollback plan).

Start Phase 6 now (release readiness) in this order:
1. Build fresh-install and restart recovery test matrix.
2. Add E2E smoke checks for MCP readiness, slash commands, and TUI startup.
3. Validate packaging channels and document rollback go/no-go gates.

Phase 6 delivered artifacts so far:
1. Release-readiness CI workflow: `.github/workflows/release-readiness.yml`.
2. Matrix runner script: `scripts/e2e/release_readiness_matrix.py`.
3. Packaging channels script: `scripts/package_cli_bundle.py`.
4. Release candidate + rollback runbook: `RELEASE_CANDIDATE_PLAN.md`.

