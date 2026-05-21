# Installation

Step-by-step installation guide for all supported platforms and GPU configurations.

---

## Prerequisites

All platforms require:
- Python 3.10+
- Git
- `curl`
- `unzip`
- `cmake` 3.18+ (for building llama.cpp from source)
- C/C++ compiler (`gcc`/`g++` 11+ or `clang` 14+)
- Node.js 18+ and `npm` (frontend only)
- 4GB+ VRAM recommended (NVIDIA or AMD); CPU-only is supported but slow

---

## One-command installer (recommended)

The installer auto-detects your GPU, downloads a prebuilt `llama-server`, installs the orchestrator and CLI into `~/.local/share/atri/`, and symlinks the `atri` command into `~/.local/bin/`.

```bash
curl -fsSL https://raw.githubusercontent.com/ToniBirat7/Agentic_AI/master/install.sh | bash
```

The model (`gemma-4-e2b-it-Q4_K_M.gguf`, ~2.5 GB) is fetched on first run.

---

## Manual installation — from source

### 1. Clone

```bash
git clone https://github.com/ToniBirat7/Agentic_AI.git
cd Agentic_AI
git submodule update --init --recursive   # pulls llama.cpp
```

### 2. Install dependencies

```bash
make install
```

This creates `services/orchestrator/.venv`, installs Python packages, installs the `atri` CLI package, and symlinks `~/.local/bin/atri`.

### 3. Configure environment

```bash
cp services/orchestrator/.env.example services/orchestrator/.env
# Edit .env if needed — defaults work for local dev
```

### 4. Download the model

```bash
mkdir -p models
# Download from HuggingFace:
# https://huggingface.co/lmstudio-ai/gemma-4-e2b-it-GGUF
# File: gemma-4-e2b-it-Q4_K_M.gguf (~2.5 GB)
# Place at: models/gemma-4-e2b-it-Q4_K_M.gguf
```

### 5. Build llama.cpp (pick your GPU variant below)

### 6. Start services

```bash
make dev-up   # or: make cli-up (no frontend)
atri
```

---

## GPU variants

### NVIDIA CUDA

**Requirements:** CUDA Toolkit 12.x, driver 525+, `nvcc` on PATH.

```bash
# Verify CUDA is available
nvcc --version
nvidia-smi

# Build llama.cpp with CUDA
make llama-build-gpu                       # RTX 30xx / 20xx (arch 86/80)
LLAMA_CUDA_ARCH=89 make llama-build-gpu   # RTX 40xx
LLAMA_CUDA_ARCH=75 make llama-build-gpu   # RTX 20xx (Turing)
LLAMA_CUDA_ARCH=61 make llama-build-gpu   # GTX 10xx (Pascal)
```

Expected output: `[100%] Built target llama-server` with no CUDA errors.

To confirm GPU offloading is active, check `llama.log` after `make dev-up`:

```
llm_load_tensors: offloaded 18/18 layers to GPU
```

### AMD ROCm

**Requirements:** ROCm 5.6+, `rocm-dev` package, `hipcc` on PATH.

```bash
# Install ROCm (Arch)
yay -S rocm-hip-sdk rocm-opencl-sdk

# Install ROCm (Ubuntu 22.04)
wget https://repo.radeon.com/amdgpu-install/6.0/ubuntu/jammy/amdgpu-install_6.0.60000-1_all.deb
sudo dpkg -i amdgpu-install*.deb
sudo amdgpu-install --usecase=rocm

# Build llama.cpp with ROCm
cd runtime/llm/llama.cpp
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON \
      -DGGML_HIPBLAS=ON -DAMDGPU_TARGETS="gfx1031"   # RX 6000 series
cmake --build build --config Release -j$(nproc) --target llama-server llama-cli
```

ROCm target codes: `gfx1030` (RX 6800/6900), `gfx1031` (RX 6700), `gfx1100` (RX 7900 series).

### Apple Silicon (Metal / MPS)

**Requirements:** macOS 12.3+, Xcode Command Line Tools.

```bash
xcode-select --install

cd runtime/llm/llama.cpp
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DGGML_METAL=ON
cmake --build build --config Release -j$(sysctl -n hw.logicalcpu) --target llama-server llama-cli
```

All parameters are the same as Linux; Metal handles GPU offloading automatically (`--n-gpu-layers 999`).

### CPU-only fallback

```bash
cd runtime/llm/llama.cpp
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j$(nproc) --target llama-server llama-cli
```

Set thread count in `Makefile` or `.env`:
- `LLAMA_THREADS` = number of physical cores (not hyperthreaded)
- `LLAMA_N_GPU_LAYERS=0` to disable GPU offloading

Expected throughput: ~3–8 tok/s on a modern 6-core CPU.

---

## Linux

### Arch / Manjaro

```bash
sudo pacman -Syu --needed base-devel cmake cuda git python nodejs npm
# ROCm alternative: yay -S rocm-hip-sdk
git clone https://github.com/ToniBirat7/Agentic_AI.git && cd Agentic_AI
git submodule update --init --recursive
make install
make llama-build-gpu
```

### Ubuntu 22.04 / 24.04

```bash
sudo apt update && sudo apt install -y build-essential cmake git python3 python3-venv \
     python3-pip nodejs npm curl unzip
# CUDA: install nvidia-cuda-toolkit separately from nvidia.com or apt
git clone https://github.com/ToniBirat7/Agentic_AI.git && cd Agentic_AI
git submodule update --init --recursive
make install
make llama-build-gpu
```

### Fedora 39+

```bash
sudo dnf groupinstall "Development Tools"
sudo dnf install cmake git python3 python3-pip nodejs npm curl unzip
# CUDA: install from nvidia.com RPM repo
git clone https://github.com/ToniBirat7/Agentic_AI.git && cd Agentic_AI
git submodule update --init --recursive
make install
make llama-build-gpu
```

---

## macOS (Apple Silicon + Intel)

```bash
xcode-select --install
brew install cmake git python@3.11 node

git clone https://github.com/ToniBirat7/Agentic_AI.git && cd Agentic_AI
git submodule update --init --recursive
make install

# Build with Metal (Apple Silicon) or CPU (Intel)
cd runtime/llm/llama.cpp
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DGGML_METAL=ON
cmake --build build -j$(sysctl -n hw.logicalcpu) --target llama-server llama-cli
cd ../../..

make dev-up
atri
```

**Intel Mac note:** Drop `-DGGML_METAL=ON` and set `LLAMA_N_GPU_LAYERS=0` in the Makefile. Inference will use AVX2.

---

## WSL2 (Windows Subsystem for Linux)

1. Install WSL2 with Ubuntu 22.04 from the Microsoft Store.
2. Install the [NVIDIA CUDA driver for WSL2](https://developer.nvidia.com/cuda/wsl).
3. Follow the Ubuntu instructions above inside WSL2.

```bash
# Verify CUDA is visible inside WSL2
nvidia-smi
nvcc --version
```

Port forwarding is automatic — `http://localhost:8001` in your Windows browser reaches the orchestrator.

---

## Common gotchas per platform

### Linux (all)

- **`make install` fails with `externally-managed-environment`:** Use `python3 -m venv` explicitly or pass `--break-system-packages` (not recommended). The Makefile already uses a venv — this error means you ran `pip install` manually outside the venv.
- **`atri` command not found after install:** Ensure `~/.local/bin` is on your `PATH`. Add `export PATH="$HOME/.local/bin:$PATH"` to `~/.bashrc` or `~/.zshrc`.
- **CUDA `nvcc` not on PATH:** `export PATH="/usr/local/cuda/bin:$PATH"` and `export LD_LIBRARY_PATH="/usr/local/cuda/lib64:$LD_LIBRARY_PATH"`.

### macOS

- **`cmake` not found:** `brew install cmake`.
- **Metal fails on Intel Mac:** Intel Macs do not have MPS. Remove `-DGGML_METAL=ON` from the cmake command.
- **`npm` not found:** `brew install node`.
- **Slow inference on Apple Silicon:** Ensure Xcode CLI tools are installed and cmake picked up Metal (`GGML_METAL=ON` in cmake output).

### WSL2

- **`nvidia-smi` not found inside WSL2:** Install the Windows NVIDIA driver (not the Linux one). The WSL2 CUDA layer is provided by the Windows driver.
- **Port conflicts:** Windows may already use port 3000. Change `FRONTEND_PORT` in the Makefile.

---

## Verifying the installation

```bash
# Check all services are healthy
make health

# Expected output:
#  LLM (llama.cpp)    "local-model"
#  Orchestrator       "ok"
#  Frontend           200

# Open the TUI
atri
```

---

## Related pages

- [[troubleshooting]] — per-error fixes
- [[performance]] — GPU layer count, KV cache tuning
- [[configuration]] — .env variables
