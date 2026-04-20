# Security Policy

## Scope

This repository enforces local-first security hygiene for Atri Code runtime and tooling.

## Secrets Management Rules

- Never commit live credentials, API keys, private keys, or tokens.
- Use environment variables for runtime credentials.
- Use local `.env` files for development overrides.
- Keep `.env` files out of source control.

## Approved Placeholder Values

For docs/examples only, these placeholders are allowed:

- `__SET_ME__`
- `replace-me`
- `change-me-in-production`
- `replace-with-a-long-random-secret`

## Reporting

If you find a leaked credential:

1. Revoke/rotate it immediately.
2. Remove it from tracked files.
3. Add a fix commit and note the rotation in the PR.
4. Re-run `python scripts/scan_secrets.py` and CI checks.

## Local Validation

Run before commit:

```bash
pre-commit run --all-files
python scripts/scan_secrets.py
```
