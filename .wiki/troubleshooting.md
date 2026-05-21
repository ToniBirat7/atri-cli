# Troubleshooting

Per-error reference. Each entry: symptom, root cause, fix.

---

## GCC version incompatibility with CUDA

**Symptom:**

```
error: #error -- unsupported GNU version! gcc versions later than 12 are not supported!
```

or cmake fails during CUDA compilation with a GCC version error.

**Root cause:** Each CUDA Toolkit version supports only specific GCC versions. CUDA 12.2 supports up to GCC 12. CUDA 12.4+ supports GCC 13. If your system GCC is newer than the CUDA toolkit allows, nvcc rejects it.

**Fix:**

```bash
# Check versions
gcc --version
nvcc --version

# Option 1: install and use an older GCC (Arch)
sudo pacman -S gcc12
export CC=gcc-12
export CXX=g++-12
make llama-build-gpu

# Option 1b: Ubuntu
sudo apt install gcc-12 g++-12
export CC=gcc-12 CXX=g++-12
make llama-build-gpu

# Option 2: upgrade CUDA toolkit to match your GCC
# Install CUDA 12.4+ from https://developer.nvidia.com/cuda-downloads
```

---

## VRAM insufficient — model too large

**Symptom:**

```
CUDA error: out of memory
# or in llama.log:
llm_load_tensors: failed to allocate CUDA buffer
```

The model partially loads, then the server crashes or inference is extremely slow (CPU fallback).

**Root cause:** The quantized model weights exceed available VRAM. `gemma-4-e2b-it-Q4_K_M.gguf` requires ~2.5 GB for weights alone, plus KV cache overhead. With `--ctx-size 32768` and `q8_0` KV cache, total VRAM can reach 4–5 GB.

**Fix:**

```bash
# Option 1: reduce context size
# In Makefile, lower LLAMA_CTX_SIZE:
LLAMA_CTX_SIZE ?= 8192    # from 32768

# Option 2: use smaller KV cache quantization
LLAMA_CTK ?= q4_0
LLAMA_CTV ?= q4_0

# Option 3: offload fewer layers to GPU
LLAMA_N_GPU_LAYERS ?= 14  # from 999 (all); experiment with lower values

# Option 4: disable Flash Attention (frees some VRAM)
# Remove --flash-attn from the llama-server command in Makefile
```

Check actual VRAM usage:

```bash
nvidia-smi --query-gpu=memory.used,memory.total --format=csv
```

---

## Network timeout during model download

**Symptom:** `curl` or the installer script hangs or fails with:

```
curl: (28) Operation timed out after 30000 milliseconds
# or
Error: incomplete download, expected X bytes
```

**Root cause:** The model file is 2.5–3 GB. Slow connections or proxy interference cause timeouts.

**Fix:**

```bash
# Option 1: download manually with resume support
curl -L --retry 5 --retry-delay 10 --continue-at - \
  https://huggingface.co/lmstudio-ai/gemma-4-e2b-it-GGUF/resolve/main/gemma-4-e2b-it-Q4_K_M.gguf \
  -o models/gemma-4-e2b-it-Q4_K_M.gguf

# Option 2: use huggingface-cli (handles auth, checksums, resume)
pip install huggingface_hub
huggingface-cli download lmstudio-ai/gemma-4-e2b-it-GGUF gemma-4-e2b-it-Q4_K_M.gguf \
  --local-dir models/

# Option 3: download via browser/torrent and place at models/gemma-4-e2b-it-Q4_K_M.gguf
```

Verify integrity:

```bash
# File should be ~2.4–2.7 GB
ls -lh models/gemma-4-e2b-it-Q4_K_M.gguf
```

---

## CUDA architecture mismatch (8.6 vs 86)

**Symptom:**

```
CUDA error: no kernel image is available for execution on the device
# or in llama.log:
CUDA kernel launch failed: invalid device function
```

**Root cause:** The llama.cpp binary was compiled for a different CUDA compute capability than your GPU. The `LLAMA_CUDA_ARCH` Makefile variable uses the integer form (`86`) not the dotted form (`8.6`). Confusion between the two is common. Additionally, prebuilt binaries may target a different arch.

**Fix:**

```bash
# Find your GPU's compute capability
nvidia-smi --query-gpu=compute_cap --format=csv,noheader
# Example output: 8.6  → use LLAMA_CUDA_ARCH=86

# Rebuild for your specific GPU
LLAMA_CUDA_ARCH=86 make llama-build-gpu    # RTX 3060 / 3080 / A100
LLAMA_CUDA_ARCH=89 make llama-build-gpu    # RTX 4090 / 4080
LLAMA_CUDA_ARCH=75 make llama-build-gpu    # RTX 20xx (Turing)
LLAMA_CUDA_ARCH=61 make llama-build-gpu    # GTX 10xx (Pascal)
LLAMA_CUDA_ARCH=80 make llama-build-gpu    # A100
```

---

## Port conflicts — 8000/8001/3000 already in use

**Symptom:**

```
ERROR:    [Errno 98] Address already in use
# or in llama.log:
bind: address already in use
```

**Root cause:** Another process is using one of the service ports (8000 = llama-server, 8001 = orchestrator, 3000 = frontend). Common culprits: a previous `make dev-up` that wasn't cleanly stopped, or another service (e.g. a different development server).

**Fix:**

```bash
# Cleanly stop all Atri services
make dev-down

# Or kill by port individually
lsof -ti tcp:8000 | xargs -r kill
lsof -ti tcp:8001 | xargs -r kill
lsof -ti tcp:3000 | xargs -r kill

# If you want to use different ports, override in Makefile:
LLAMA_PORT ?= 8010
ORCHESTRATOR_PORT ?= 8011
FRONTEND_PORT ?= 3010
# Then update LLM_BASE_URL in .env accordingly:
# LLM_BASE_URL=http://127.0.0.1:8010/v1
```

---

## `make install` fails — missing build tools

**Symptom:**

```
cmake: command not found
# or
gcc: command not found
# or
fatal error: Python.h: No such file or directory
```

**Root cause:** The system is missing C/C++ build tools, cmake, or Python development headers. These are required to compile llama.cpp and some Python C extensions.

**Fix — Arch:**

```bash
sudo pacman -S --needed base-devel cmake python
```

**Fix — Ubuntu/Debian:**

```bash
sudo apt update
sudo apt install -y build-essential cmake python3-dev python3-venv pkg-config
```

**Fix — Fedora:**

```bash
sudo dnf groupinstall "Development Tools"
sudo dnf install cmake python3-devel
```

**Fix — macOS:**

```bash
xcode-select --install
brew install cmake python@3.11
```

After installing missing tools, re-run `make install`.

---

## Orchestrator fails to connect to LLM (`llm_connected: false`)

**Symptom:** `curl http://127.0.0.1:8001/health` returns `"llm_connected": false`.

**Root cause:** llama-server is not running, or it started on a different port than `LLM_BASE_URL` in `.env`.

**Fix:**

```bash
# Check if llama-server is running
lsof -i tcp:8000

# If not running, start it
make llama

# Check LLM_BASE_URL in .env matches the actual port
grep LLM_BASE_URL services/orchestrator/.env
# Should be: LLM_BASE_URL=http://127.0.0.1:8000/v1

# Tail llama.log to see startup errors
tail -50 llama.log
```

---

## Silent empty response from `/chat`

**Symptom:** `/chat` returns `{"turns": null, "response": ""}` or an empty SSE stream. No error in orchestrator.log.

**Root cause:** `LLM_TIMEOUT_SECONDS` is too low for the model + hardware combination. The agent loop receives a timeout exception and returns an empty result.

**Fix:**

```bash
# In services/orchestrator/.env:
LLM_TIMEOUT_SECONDS=300

# Restart orchestrator
make dev-down && make dev-up
```

For large MoE models (26B+) on hybrid CPU/GPU hardware, use 300–600 seconds.

---

## `get_file_info` field name error

**Symptom:**

```
ValueError: Unexpected fields for tool 'get_file_info': path. Valid fields are: target_path
```

**Root cause:** The model hallucinates `path` (the common convention) instead of `target_path` (the actual schema field). This is a model behavior issue, not a code bug.

**Workaround:** The agent loop catches this and retries on the next turn. No user action required. The model usually self-corrects.

---

## `--jinja` flag missing — tool calls not working

**Symptom:** The model responds in plain text instead of calling tools. No `tool_calls` appear in the LLM response.

**Root cause:** Gemma 4 requires the `--jinja` flag on llama-server for tool-calling support. Without it, the model generates the chat template incorrectly and tool calls are never emitted.

**Fix:** Ensure llama-server is started with `--jinja`. The Makefile includes this by default:

```bash
# In Makefile dev-up target:
./build/bin/llama-server -m ... --jinja ...
```

If you started llama-server manually without `--jinja`, restart it with the flag.

---

## Related pages

- [[installation]] — per-platform setup
- [[performance]] — VRAM and context size tuning
- [[known-issues]] — open bugs and workarounds
- [[configuration]] — .env variables
