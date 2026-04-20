# Scripts

Use this folder for helper scripts such as:
- local startup scripts
- environment bootstrap scripts
- evaluation helpers

## Benchmarks

Run orchestrator-only benchmark:

```bash
"/run/media/tonibirat/New Volume/AI_ML_Complete/Agentic_AI/.env/bin/python" scripts/benchmarks/benchmark_orchestrator_e2e.py
```

Run full pipeline benchmark (frontend -> orchestrator -> llama):

```bash
"/run/media/tonibirat/New Volume/AI_ML_Complete/Agentic_AI/.env/bin/python" scripts/benchmarks/benchmark_full_pipeline.py
```

Run both and write reports to `benchmark_reports/`:

```bash
"/run/media/tonibirat/New Volume/AI_ML_Complete/Agentic_AI/.env/bin/python" scripts/benchmarks/run_benchmarks.py
```

Optional environment variables:

- `ORCHESTRATOR_BENCH_BASE_URL` (default: `http://127.0.0.1:8001`)
- `ORCHESTRATOR_BENCH_AUTH_TOKEN` (Bearer token if auth is enabled)
- `FRONTEND_BENCH_BASE_URL` (default: `http://127.0.0.1:3000`)
- `LLM_BENCH_BASE_URL` (default: `http://127.0.0.1:8000`)
- `LLM_BENCH_API_KEY` (default: `secret`)

## Phase 6 Release Matrix

Run release-readiness matrix scenarios:

```bash
"/run/media/tonibirat/New Volume/AI_ML_Complete/Agentic_AI/.venv/bin/python" scripts/e2e/release_readiness_matrix.py --scenario fresh-install --python "/run/media/tonibirat/New Volume/AI_ML_Complete/Agentic_AI/.venv/bin/python"
"/run/media/tonibirat/New Volume/AI_ML_Complete/Agentic_AI/.venv/bin/python" scripts/e2e/release_readiness_matrix.py --scenario first-run --python "/run/media/tonibirat/New Volume/AI_ML_Complete/Agentic_AI/.venv/bin/python"
"/run/media/tonibirat/New Volume/AI_ML_Complete/Agentic_AI/.venv/bin/python" scripts/e2e/release_readiness_matrix.py --scenario restart --python "/run/media/tonibirat/New Volume/AI_ML_Complete/Agentic_AI/.venv/bin/python"
"/run/media/tonibirat/New Volume/AI_ML_Complete/Agentic_AI/.venv/bin/python" scripts/e2e/release_readiness_matrix.py --scenario recovery --python "/run/media/tonibirat/New Volume/AI_ML_Complete/Agentic_AI/.venv/bin/python"
```

## Packaging Channels

Build both release channels (bundled zipapp and script-installer bundle):

```bash
"/run/media/tonibirat/New Volume/AI_ML_Complete/Agentic_AI/.venv/bin/python" scripts/package_cli_bundle.py
```

Artifacts:

- `dist/atri-cli.pyz`
- `dist/atri-cli-installer.tar.gz`

## Live Readiness Harness

Boot orchestrator, run CLI smoke checks, run live stream checks (including MCP tool-call success rate),
and emit a readiness scorecard:

```bash
"/run/media/tonibirat/New Volume/AI_ML_Complete/Agentic_AI/.env/bin/python" scripts/benchmarks/live_readiness_harness.py --iterations 2
```

Include frontend boot and web smoke checks:

```bash
"/run/media/tonibirat/New Volume/AI_ML_Complete/Agentic_AI/.env/bin/python" scripts/benchmarks/live_readiness_harness.py --start-frontend --iterations 2 --report-file readiness_report.json
```

## Reset Local State

Clean local cache and database artifacts:

```bash
"/run/media/tonibirat/New Volume/AI_ML_Complete/Agentic_AI/.env/bin/python" scripts/reset_local_state.py --yes --include-frontend-build
```

Also reset docker volumes (destructive to local container data):

```bash
"/run/media/tonibirat/New Volume/AI_ML_Complete/Agentic_AI/.env/bin/python" scripts/reset_local_state.py --yes --include-frontend-build --with-docker-volumes
```
