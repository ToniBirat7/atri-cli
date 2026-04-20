# Release Candidate and Rollback Plan

## Release Candidate Flow

1. Run Security Hygiene workflow.
2. Run Release Readiness workflow.
3. Verify all checklist items in RELEASE_CHECKLIST.md.
4. Create release candidate tag: `rc-YYYYMMDD-N`.
5. Publish package artifacts from CI:
- `dist/atri-cli.pyz` (bundled channel)
- `dist/atri-cli-installer.tar.gz` (script-installer channel)

## Go/No-Go Gates

Go when all are true:

- All matrix scenarios passed: fresh-install, first-run, restart, recovery.
- MCP readiness + slash commands + TUI smoke checks passed.
- Secret scan and policy checks passed.
- Release checklist is fully green.

No-Go if any gate fails.

## Rollback Procedure

1. Identify the last known good tag.
2. Re-point deployment/docs artifact reference to last good tag.
3. Announce rollback scope and expected impact.
4. Open incident tracking issue with root-cause workstream.
5. Re-run release-readiness workflow on rollback commit.

## Ownership

- Release owner: coordinates gate review and final decision.
- Incident owner: coordinates rollback and remediation.
- Reviewer set: one CLI maintainer and one orchestrator maintainer.
