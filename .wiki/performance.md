# Performance Tuning

Reference for llama.cpp flags, KV cache strategies, thread tuning, and VRAM tradeoffs.

All settings live in the `Makefile` (overridable at `make` invocation time) or in `services/orchestrator/.env`.

---

## llama.cpp flags reference

| Flag | Default | Description |
|------|---------|-------------|
| `--threads` / `-t` | 6 | CPU threads for **token generation** (memory-bandwidth-bound). Set to physical core count, not logical. |
| `--threads-batch` / `-tb` | 12 | CPU threads for **prompt processing** (compute-bound). Set to logical thread count. |
| `--n-gpu-layers` / `-ngl` | 999 | Layers to offload to GPU. `999` = all layers. Reduce if VRAM is insufficient. |
| `--ctx-size` / `-c` | 32768 | Context window in tokens. Higher = more VRAM and compute. |
| `--cache-type-k` | `q8_0` | KV cache key quantization type. |
| `--cache-type-v` | `q8_0` | KV cache value quantization type. |
| `--flash-attn` / `-fa` | on | Enable Flash Attention 2 kernel. Requires symmetric KV types (both k and v same type). |
| `--cache-prompt` | on | Prefix caching (reuse KV cache for repeated prefixes). |
| `--cram` | 256 | Host-RAM KV prefix cache size in MB. ~93% TTFT reduction on repeated prompts. |
| `--no-mmap` | on | Disable memory-mapped model loading. Faster inference at startup cost. |
| `--parallel` | 1 | Simultaneous request slots. Keep at 1 for single-user CLI use. |
| `--api-key` | `secret` | Bearer token required for all `/v1` requests. Must match `LLM_API_KEY` in `.env`. |
| `--jinja` | on | Enable Jinja2 chat templating. **Required** for Gemma 4 tool-calling. |
| `--port` | 8000 | Server port. Must match `LLM_BASE_URL` in `.env`. |

### Makefile knobs (override at invocation)

```bash
LLAMA_THREADS=8 LLAMA_CTX_SIZE=16384 make dev-up
```

| Makefile variable | Default | Maps to flag |
|------------------|---------|-------------|
| `LLAMA_THREADS` | `6` | `--threads` |
| `LLAMA_BATCH_THREADS` | `12` | `--threads-batch` |
| `LLAMA_N_GPU_LAYERS` | `999` | `--n-gpu-layers` |
| `LLAMA_CTX_SIZE` | `32768` | `--ctx-size` |
| `LLAMA_CTK` | `q8_0` | `--cache-type-k` |
| `LLAMA_CTV` | `q8_0` | `--cache-type-v` |
| `LLAMA_CRAM` | `256` | `--cram` |
| `LLAMA_CUDA_ARCH` | `86` | cmake `CMAKE_CUDA_ARCHITECTURES` |

---

## KV cache quantization tradeoffs

The KV cache stores attention keys and values across all context tokens. Quantizing it reduces VRAM use at the cost of accuracy.

**Rule:** Flash Attention requires that `cache-type-k` and `cache-type-v` use the same type family (both float or both integer). Mixing `q4_0` + `q8_0` breaks the fused kernel and silently falls back to slower code.

| Config | VRAM (32K ctx, E2B) | Accuracy | Throughput | Notes |
|--------|---------------------|----------|------------|-------|
| `f16` / `f16` | ~6 GB | Full | Baseline | Maximum quality; often exceeds 6GB GPU VRAM |
| `q8_0` / `q8_0` | ~3.2 GB | Very high | +6% vs f16 | **Default and recommended** — Flash Attention-compatible |
| `q4_0` / `q4_0` | ~1.8 GB | High | +10% vs f16 | Good for memory-constrained setups; slight quality loss |
| `q4_0` / `f16` | — | — | — | Breaks Flash Attention; do not use |

**Default (q8_0 / q8_0):** Saves ~47% VRAM vs f16 while enabling the fused Flash Attention kernel, giving +6% throughput. Best balance for most setups.

---

## Thread tuning guide per CPU type

Token generation is **memory-bandwidth-bound**. More threads beyond physical core count does not help and often hurts due to cache thrashing.

Prompt processing is **compute-bound**. More threads (up to logical count) improves speed.

| CPU | Physical cores | Recommended `--threads` | Recommended `--threads-batch` |
|-----|---------------|------------------------|-------------------------------|
| AMD Ryzen 5 6600H | 6 | 6 | 12 |
| AMD Ryzen 9 7950X | 16 | 16 | 32 |
| Intel Core i7-12700H | 6P+8E=14 | 6 | 20 |
| Apple M2 Pro (12-core) | 8P+4E=12 | 8 | 12 |
| Apple M3 Max (16-core) | 12P+4E=16 | 12 | 16 |

**How to find physical core count:**

```bash
# Linux
lscpu | grep "Core(s) per socket"
# macOS
sysctl -n hw.physicalcpu
```

**How to check if thread count is limiting throughput:**

Run `make llama` in foreground and observe `tok/s` in the output. Try halving `--threads` — if throughput stays the same, you had too many.

---

## VRAM vs context size tradeoffs

VRAM consumption = model weights + KV cache. Model weights for `gemma-4-e2b-it-Q4_K_M.gguf` are fixed at ~2.0 GB.

KV cache size scales linearly with context length:

| Context size | KV cache (q8_0) | KV cache (q4_0) | Total VRAM (q8_0) |
|-------------|-----------------|-----------------|-------------------|
| 4096 tokens | ~0.4 GB | ~0.2 GB | ~2.4 GB |
| 8192 tokens | ~0.8 GB | ~0.4 GB | ~2.8 GB |
| 16384 tokens | ~1.6 GB | ~0.8 GB | ~3.6 GB |
| 32768 tokens | ~3.2 GB | ~1.6 GB | ~5.2 GB |

**For 4GB VRAM (RTX 3050, etc.):** Use `LLAMA_CTX_SIZE=8192` and `q4_0` KV cache.

**For 6GB VRAM (RTX 3060 Mobile):** `LLAMA_CTX_SIZE=16384` with `q8_0` is safe. 32768 is marginal — monitor with `nvidia-smi`.

**For 8GB+ VRAM:** Default `LLAMA_CTX_SIZE=32768` with `q8_0` works comfortably.

To check current VRAM use at runtime:

```bash
watch -n 1 nvidia-smi --query-gpu=memory.used,memory.total --format=csv
```

---

## Flash Attention requirements

Flash Attention (`--flash-attn`) provides significant throughput gains and memory savings for long contexts:

- ~30–50% faster attention computation
- Linear memory scaling vs quadratic without FA
- **Required:** `--cache-type-k` and `--cache-type-v` must use the **same type**
- Compatible pairs: `q8_0`/`q8_0`, `q4_0`/`q4_0`, `f16`/`f16`
- Incompatible (silently degrades): `q4_0`/`f16`, `q8_0`/`f16`

If you see this log line, Flash Attention is active:

```
ggml_cuda_flash_attn_ext: fused kernel supported
```

---

## Prefix caching (`--cram` and `--cache-prompt`)

`--cache-prompt` enables KV prefix caching: if consecutive requests share a common prefix (system prompt + recent history), the shared KV entries are reused from cache without recomputation.

`--cram 256` allocates 256 MB of host RAM for a disk-backed prefix cache, extending caching beyond what fits in VRAM. This is separate from `--cache-prompt`.

**Effect on TTFT (time to first token):**
- Cold request (no cache hit): full prompt evaluation
- Warm request (prefix cache hit): ~93% TTFT reduction (measured in E2E sessions)

The system prompt and recent session context are almost always shared across turns, so cache hit rate in the agent loop is high.

---

## Monitoring throughput

Check `llama.log` or the llama-server console for per-request timing:

```
prompt eval time =   523.42 ms /   512 tokens (    1.02 ms per token,   978.64 tokens per second)
       eval time =  2134.21 ms /   128 runs   (   16.67 ms per token,    59.97 tokens per second)
      total time =  2657.63 ms /   640 tokens
```

- **prompt eval time** = time to process the input context (prefill)
- **eval time** = time to generate the response (decode)
- **tokens per second** (eval) is the primary throughput metric

---

## Related pages

- [[installation]] — GPU-specific build instructions
- [[llm-inference]] — full llama-server launch command
- [[configuration]] — .env tunables
- [[troubleshooting]] — VRAM errors, CUDA arch mismatches
