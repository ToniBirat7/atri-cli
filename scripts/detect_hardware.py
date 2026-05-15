# Hardware detection logic
"""
Hardware detection for Atri Code build and runtime optimization.

Detects GPU vendor/capability, VRAM, CPU cores, and available RAM.
Outputs a JSON config used by the build system and llama-server launcher.

Usage:
    python scripts/detect_hardware.py              # Print JSON to stdout
    python scripts/detect_hardware.py --save       # Write to runtime/llm/launch_config.json
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def _run_quiet(cmd: list[str], timeout: int = 10) -> str:
    """Run a command and return stdout, or empty string on failure."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return result.stdout.strip()
    except Exception:
        return ""


def detect_os() -> dict:
    """Detect operating system details."""
    system = platform.system().lower()
    return {
        "os": system,
        "os_release": platform.release(),
        "arch": platform.machine(),
        "is_linux": system == "linux",
        "is_macos": system == "darwin",
        "is_windows": system == "windows",
    }


def detect_cpu() -> dict:
    """Detect CPU details."""
    cpu_count = os.cpu_count() or 4
    # Reserve 2 threads for OS/orchestrator, use rest for llama.cpp
    recommended_threads = max(2, cpu_count - 2)

    info = {
        "cpu_count": cpu_count,
        "recommended_threads": recommended_threads,
        "arch": platform.machine(),
    }

    # Check for AVX2 support on Linux
    if platform.system().lower() == "linux":
        flags = _run_quiet(["grep", "-m1", "flags", "/proc/cpuinfo"])
        info["has_avx2"] = "avx2" in flags.lower()
        info["has_avx512"] = "avx512" in flags.lower()
        info["has_fma"] = "fma" in flags.lower()
    else:
        info["has_avx2"] = True  # Assume modern CPU
        info["has_avx512"] = False
        info["has_fma"] = True

    return info


def detect_ram() -> dict:
    """Detect available RAM in MB."""
    total_mb = 0
    system = platform.system().lower()

    if system == "linux":
        meminfo = _run_quiet(["grep", "MemTotal", "/proc/meminfo"])
        if meminfo:
            try:
                total_kb = int(meminfo.split()[1])
                total_mb = total_kb // 1024
            except (IndexError, ValueError):
                pass
    elif system == "darwin":
        raw = _run_quiet(["sysctl", "-n", "hw.memsize"])
        if raw:
            try:
                total_mb = int(raw) // (1024 * 1024)
            except ValueError:
                pass
    elif system == "windows":
        raw = _run_quiet(
            ["wmic", "ComputerSystem", "get", "TotalPhysicalMemory", "/value"]
        )
        for line in raw.splitlines():
            if "TotalPhysicalMemory" in line:
                try:
                    total_mb = int(line.split("=")[1]) // (1024 * 1024)
                except (IndexError, ValueError):
                    pass

    return {"total_ram_mb": total_mb, "total_ram_gb": round(total_mb / 1024, 1)}


def detect_nvidia_gpu() -> dict | None:
    """Detect NVIDIA GPU via nvidia-smi."""
    if not shutil.which("nvidia-smi"):
        return None

    # Get GPU name
    name = _run_quiet(
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader,nounits"]
    )
    if not name:
        return None

    # Get VRAM in MB
    vram_str = _run_quiet(
        ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"]
    )
    vram_mb = 0
    try:
        vram_mb = int(vram_str.strip().split("\n")[0])
    except (ValueError, IndexError):
        pass

    # Get compute capability
    compute_cap = _run_quiet(
        [
            "nvidia-smi",
            "--query-gpu=compute_cap",
            "--format=csv,noheader,nounits",
        ]
    )
    compute_cap = compute_cap.strip().split("\n")[0] if compute_cap else ""

    # Derive cmake CUDA architecture (e.g., "8.6" -> "86")
    cuda_arch = ""
    if compute_cap and "." in compute_cap:
        cuda_arch = compute_cap.replace(".", "")

    # Check if nvcc is available
    has_nvcc = shutil.which("nvcc") is not None

    return {
        "vendor": "nvidia",
        "name": name.strip().split("\n")[0],
        "vram_mb": vram_mb,
        "compute_capability": compute_cap,
        "cuda_architecture": cuda_arch,
        "has_nvcc": has_nvcc,
    }


def detect_amd_gpu() -> dict | None:
    """Detect AMD GPU via rocm-smi."""
    if not shutil.which("rocm-smi"):
        return None

    name = _run_quiet(["rocm-smi", "--showproductname"])
    if not name or "ERROR" in name.upper():
        return None

    vram_str = _run_quiet(["rocm-smi", "--showmeminfo", "vram"])
    vram_mb = 0
    for line in vram_str.splitlines():
        if "Total" in line:
            try:
                parts = line.split()
                vram_mb = int(parts[-2]) // (1024 * 1024)
            except (ValueError, IndexError):
                pass

    return {"vendor": "amd", "name": name.strip(), "vram_mb": vram_mb}


def detect_apple_gpu() -> dict | None:
    """Detect Apple Silicon GPU."""
    if platform.system().lower() != "darwin":
        return None

    cpu_brand = _run_quiet(["sysctl", "-n", "machdep.cpu.brand_string"])
    if not cpu_brand or "Apple" not in cpu_brand:
        return None

    # Apple Silicon uses unified memory
    ram_raw = _run_quiet(["sysctl", "-n", "hw.memsize"])
    unified_mem_mb = 0
    try:
        unified_mem_mb = int(ram_raw) // (1024 * 1024)
    except ValueError:
        pass

    return {
        "vendor": "apple",
        "name": cpu_brand.strip(),
        "vram_mb": unified_mem_mb,  # Unified memory
    }


def detect_gpu() -> dict:
    """Detect any available GPU."""
    # Try NVIDIA first (most common for ML)
    nvidia = detect_nvidia_gpu()
    if nvidia:
        return {**nvidia, "detected": True}

    # Try AMD
    amd = detect_amd_gpu()
    if amd:
        return {**amd, "detected": True}

    # Try Apple Silicon
    apple = detect_apple_gpu()
    if apple:
        return {**apple, "detected": True}

    return {"detected": False, "vendor": "none", "name": "CPU only", "vram_mb": 0}


def compute_launch_config(
    gpu: dict, cpu: dict, ram: dict, model_size_mb: int = 16384
) -> dict:
    """Compute optimal llama-server launch parameters based on hardware.

    Tuned for Gemma 4 26B A4B MoE (UD-Q4_K_M):
      - Main GGUF: ~16.9 GB on disk, ~6-8 GB VRAM with -ngl 999 + --n-cpu-moe 128
        (only non-expert layers go to GPU; 128 expert layers stay on CPU RAM)
      - Vision projector: ~1.19 GB loaded separately via --mmproj
      - KV cache: q4_0/q8_0 to conserve the remaining VRAM headroom
      - Unified memory (GGML_CUDA_ENABLE_UNIFIED_MEMORY=1) set by launcher
    """
    gpu_detected = gpu.get("detected", False)
    vendor = gpu.get("vendor", "none")
    vram_mb = gpu.get("vram_mb", 0)

    if gpu_detected and vendor == "nvidia" and vram_mb >= 5000:
        # With GGML_CUDA_ENABLE_UNIFIED_MEMORY=1 + --n-cpu-moe 128, expert layers
        # stay in CPU RAM and non-expert layers use GPU VRAM.
        # Empirically verified on RTX 3060 6 GB: 32K context leaves ~1 GB VRAM free.
        # Unified memory lets KV cache overflow to system RAM on Ampere+.
        if vram_mb >= 12000:
            ctx_size = 32768  # 12+ GB: comfortable headroom
        elif vram_mb >= 6000:
            ctx_size = 32768  # 6 GB: verified empirically with q4_0/q8_0 KV cache
        else:
            ctx_size = 16384  # 5 GB: conservative
    elif gpu_detected and vendor == "apple":
        # Apple Silicon: unified memory means more headroom
        total_unified = vram_mb
        if total_unified >= 32000:
            ctx_size = 32768
        elif total_unified >= 16000:
            ctx_size = 16384
        else:
            ctx_size = 8192
    else:
        # CPU-only or AMD (ROCm MoE support varies): use RAM for context
        total_ram = ram.get("total_ram_mb", 8192)
        if total_ram >= 64000:
            ctx_size = 16384
        elif total_ram >= 32000:
            ctx_size = 8192
        else:
            ctx_size = 4096

    # All layers offloaded; MoE expert layers stay on CPU via --n-cpu-moe
    n_gpu_layers = 999 if gpu_detected else 0

    # Batch / ubatch size
    batch_size = 2048 if gpu_detected else 512
    ubatch_size = 512

    # Flash attention: available on NVIDIA Ampere+ (SM >= 80) and Apple Metal
    flash_attn = False
    if vendor == "nvidia":
        compute_cap = gpu.get("compute_capability", "")
        try:
            major = int(compute_cap.split(".")[0]) if "." in compute_cap else 0
            flash_attn = major >= 8
        except (ValueError, IndexError):
            flash_attn = False
    elif vendor == "apple":
        flash_attn = True  # Metal supports it

    # MoE KV cache: q4_0 for keys (lookup only), q8_0 for values (computation)
    # This is more aggressive than q8_0/q8_0 but necessary to fit context on 6 GB VRAM.
    kv_cache_type_k = "q4_0" if gpu_detected else "f16"
    kv_cache_type_v = "q8_0" if gpu_detected else "f16"

    # Thread count: MoE expert computation benefits from more CPU threads.
    # Diminishing returns above 8 threads; cap there.
    cpu_count = cpu.get("cpu_count", 4)
    threads = min(max(2, cpu_count - 2), 8)

    config = {
        "gpu_detected": gpu_detected,
        "gpu_vendor": vendor,
        "gpu_name": gpu.get("name", ""),
        "gpu_vram_mb": vram_mb,
        "compute_capability": gpu.get("compute_capability", ""),
        "cuda_architecture": gpu.get("cuda_architecture", ""),
        "cpu_threads": cpu_count,
        "recommended_n_gpu_layers": n_gpu_layers,
        "recommended_ctx_size": ctx_size,
        "recommended_batch_size": batch_size,
        "recommended_ubatch_size": ubatch_size,
        "recommended_threads": threads,
        "flash_attn": flash_attn,
        "kv_cache_type_k": kv_cache_type_k,
        "kv_cache_type_v": kv_cache_type_v,
        # MoE-specific: pin all 128 expert layers to CPU RAM
        "n_cpu_moe": 128,
        # MoE best practice: no memory mapping; load entire model into RAM
        "no_mmap": True,
        # Pin model to RAM; prevents paging under memory pressure
        "mlock": True,
        # Single parallel slot; MoE is memory-intensive
        "parallel_slots": 1,
        # Whether to set GGML_CUDA_ENABLE_UNIFIED_MEMORY (NVIDIA only)
        "enable_unified_memory": vendor == "nvidia",
        "enable_thinking": True,
    }

    return config


def compute_cmake_args(gpu: dict, cpu: dict) -> list[str]:
    """Compute cmake arguments for building llama.cpp."""
    args = [
        "-DCMAKE_BUILD_TYPE=Release",
        "-DBUILD_SHARED_LIBS=OFF",
        "-DLLAMA_BUILD_TESTS=OFF",
        "-DLLAMA_BUILD_EXAMPLES=OFF",
        "-DLLAMA_BUILD_SERVER=ON",
    ]

    vendor = gpu.get("vendor", "none")

    if vendor == "nvidia" and gpu.get("has_nvcc", False):
        args.append("-DGGML_CUDA=ON")
        cuda_arch = gpu.get("cuda_architecture", "")
        if cuda_arch:
            args.append(f"-DCMAKE_CUDA_ARCHITECTURES={cuda_arch}")
        args.append("-DGGML_NATIVE=ON")

    elif vendor == "amd":
        args.append("-DGGML_HIP=ON")
        args.append("-DGGML_NATIVE=ON")

    elif vendor == "apple":
        args.append("-DGGML_METAL=ON")
        args.append("-DGGML_NATIVE=ON")

    else:
        # CPU-only build
        args.append("-DGGML_CUDA=OFF")
        args.append("-DGGML_NATIVE=ON")
        args.append("-DGGML_OPENMP=ON")

    return args


def detect_all() -> dict:
    """Run full hardware detection and return complete config."""
    os_info = detect_os()
    cpu_info = detect_cpu()
    ram_info = detect_ram()
    gpu_info = detect_gpu()
    launch_config = compute_launch_config(gpu_info, cpu_info, ram_info)
    cmake_args = compute_cmake_args(gpu_info, cpu_info)

    return {
        "os": os_info,
        "cpu": cpu_info,
        "ram": ram_info,
        "gpu": gpu_info,
        "launch_config": launch_config,
        "cmake_args": cmake_args,
    }


def main() -> int:
    hw = detect_all()

    if "--save" in sys.argv:
        # Determine save root: prefer --install-root <path> if provided,
        # otherwise fall back to the repo root (dev layout).
        save_root: Path | None = None
        if "--install-root" in sys.argv:
            idx = sys.argv.index("--install-root")
            if idx + 1 < len(sys.argv):
                save_root = Path(sys.argv[idx + 1]).expanduser().resolve()

        if save_root is None:
            script_dir = Path(__file__).resolve().parent
            save_root = script_dir.parent  # repo root

        config_path = save_root / "runtime" / "llm" / "launch_config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(hw["launch_config"], indent=2) + "\n", encoding="utf-8"
        )
        print(f"[detect-hw] Saved launch config to {config_path}")

    print(json.dumps(hw, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
