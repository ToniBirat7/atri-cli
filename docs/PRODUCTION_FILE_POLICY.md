# Production File Policy

This repository is maintained as production-focused source code.

## Keep In Git

- Application code (`apps/`, `services/`, `runtime/` sources)
- Build and deployment config (`Makefile`, `docker-compose.yml`, `deploy/`)
- End-user documentation (`README.md`, `QUICKSTART.md`, selected `docs/`)

## Keep Local Only (Ignored)

- Runtime databases: `*.db`, `*.db-shm`, `*.db-wal`, `*.sqlite*`
- Logs and process files: `*.log`, `logs/`, `*.pid`
- Build/cache artifacts: `.venv/`, `node_modules/`, `.next/`, llama build outputs
- Large local model files: `*.gguf`, `*.ggml`, `*.bin`

## Release Hygiene Checklist

- Ensure `git status` is clean before pushing
- Verify no runtime artifacts are tracked: `git ls-files | rg "\\.db($|-)|\\.log$|\\.sqlite"`
- Keep only branch-relevant top-level docs (`README.md`, `QUICKSTART.md`)