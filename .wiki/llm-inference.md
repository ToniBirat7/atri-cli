# LLM Inference

**Binary:** `runtime/llm/llama.cpp/build/bin/llama-server`  
**Port:** 8080  
**API:** OpenAI-compatible `/v1/chat/completions`, `/v1/models`, `/health`

## Hardware

| Component | Spec |
|-----------|------|
| GPU | NVIDIA RTX 3060 Laptop, 6 GB VRAM, CUDA arch 86 |
| CPU | AMD Ryzen 5 6600H (6 cores / 12 threads) |
| RAM | 32 GB |
| Storage | TOSHIBA_EXT USB drive (model files) |

## Model files

```
/run/media/tonibirat/TOSHIBA_EXT/Gemma4_MoE_Models/
  gemma-4-26B-A4B-it-UD-Q4_K_M.gguf   # 26B MoE weights
  mmproj-BF16.gguf                      # multimodal projector (vision)
```

## Launch command (MoE hybrid mode)

```bash
export GGML_CUDA_ENABLE_UNIFIED_MEMORY=1

cd runtime/llm/llama.cpp

nohup ./build/bin/llama-server \
  -m /run/media/tonibirat/TOSHIBA_EXT/Gemma4_MoE_Models/gemma-4-26B-A4B-it-UD-Q4_K_M.gguf \
  --mmproj /run/media/tonibirat/TOSHIBA_EXT/Gemma4_MoE_Models/mmproj-BF16.gguf \
  -ngl 999 \
  --n-cpu-moe 118 \
  -c 32768 \
  -np 1 \
  -ctk q4_0 \
  -ctv q8_0 \
  -fa on \
  --no-mmap \
  --mlock \
  -t 6 \
  --host 0.0.0.0 \
  --port 8080 \
  --api-key secret \
  > ../../../llama.log 2>&1 &
```

## Flag rationale

| Flag | Value | Why |
|------|-------|-----|
| `-ngl 999` | offload all layers | Puts attention layers on GPU (~2.4 GB VRAM) |
| `--n-cpu-moe 118` | all 118 expert layers to CPU | MoE experts (~14.4 GB) don't fit on 6 GB GPU |
| `GGML_CUDA_ENABLE_UNIFIED_MEMORY=1` | env var | GPU can spill to system RAM if needed |
| `--no-mmap` | disable memory-mapped IO | Avoids page faults on slow USB drive reads mid-inference |
| `--mlock` | lock buffer in RAM | Prevents OS from paging model weights back to disk |
| `-ctk q4_0 -ctv q8_0` | KV cache quantization | Reduces VRAM usage for the KV cache |
| `-fa on` | flash attention | Further VRAM reduction on attention layers |
| `-c 32768` | context window | Full 32K tokens |
| `-np 1` | single parallel slot | Only one request in flight at a time (queue serializes) |
| `-t 6` | CPU threads | For MoE expert computation on CPU |

## Expected behavior

- **Load time:** ~60–120 seconds (slow USB → system RAM)
- **`--mlock` warning:** `warning: failed to mlock 15137390592-byte buffer` — non-fatal; OS partial-locks what it can
- **Throughput:** ~5–8 tok/s on this hardware (attention on GPU, experts on CPU)
- **Concurrent requests:** queued (np=1), not parallel

## Health check

```bash
curl http://127.0.0.1:8080/health
# → {"status":"ok"}
```

## `.env` wiring

```
LLM_BASE_URL=http://127.0.0.1:8080/v1
LLM_API_KEY=secret
LLM_TIMEOUT_SECONDS=300
```

The default `LLM_BASE_URL` in the codebase is `:8000` — it must be patched to `:8080` to match this launch command.

## Related pages

- [[architecture]] — how llama-server fits into the stack
- [[configuration]] — LLM_* env vars
- [[known-issues]] — mlock warning, timeout, port mismatch fix
