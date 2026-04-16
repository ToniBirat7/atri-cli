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

## Reset Local State

Clean local cache and database artifacts:

```bash
"/run/media/tonibirat/New Volume/AI_ML_Complete/Agentic_AI/.env/bin/python" scripts/reset_local_state.py --yes --include-frontend-build
```

Also reset docker volumes (destructive to local container data):

```bash
"/run/media/tonibirat/New Volume/AI_ML_Complete/Agentic_AI/.env/bin/python" scripts/reset_local_state.py --yes --include-frontend-build --with-docker-volumes
```
