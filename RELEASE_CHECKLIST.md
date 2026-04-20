# Release Checklist

## Security

- [ ] `python scripts/scan_secrets.py` passes.
- [ ] No live credentials in tracked files.
- [ ] Required environment variables documented.
- [ ] Any rotated credentials have been replaced in deployment secrets.

## CI

- [ ] Security Hygiene workflow passed.
- [ ] Orchestrator CI workflow passed.
- [ ] Release Readiness workflow passed for all matrix scenarios.
- [ ] Targeted CLI/orchestrator tests passed for changed areas.

## Release Readiness

- [ ] Fresh-install scenario passed.
- [ ] First-run scenario passed.
- [ ] Restart scenario passed.
- [ ] Recovery scenario passed.
- [ ] MCP readiness smoke checks passed.
- [ ] Slash command smoke checks passed.
- [ ] TUI smoke checks passed.

## Packaging

- [ ] Script installer channel artifact built (`atri-cli-installer.tar.gz`).
- [ ] Bundled binary channel artifact built (`atri-cli.pyz`).
- [ ] Bundled binary channel starts (`python dist/atri-cli.pyz --help`).

## Runtime Hygiene

- [ ] `atri-cli cleanup --mode safe --yes` works locally.
- [ ] Runtime junk files are ignored by `.gitignore`.
- [ ] No accidental DB/log artifacts are included in release commit.

## Rollback

- [ ] Rollback tag/commit identified.
- [ ] Rollback steps tested or rehearsed.
- [ ] Incident owner and communication path defined.
- [ ] Release candidate and rollback plan reviewed (`RELEASE_CANDIDATE_PLAN.md`).
