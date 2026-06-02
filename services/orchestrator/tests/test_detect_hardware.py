"""Model-agnostic launch-config tests for scripts/detect_hardware.py.

Covers the dense (E2B) vs MoE (26B) branching: --n-cpu-moe gating, mlock,
and the VRAM-fit vs RAM-spill context-size strategy.
"""
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from detect_hardware import compute_launch_config


_NVIDIA_6GB = {
    "detected": True, "vendor": "nvidia", "vram_mb": 6144,
    "compute_capability": "8.6", "cuda_architecture": "86", "name": "RTX 3060",
}
_CPU = {"cpu_count": 12, "recommended_threads": 6}
_RAM_30GB = {"total_ram_mb": 31000}
_RAM_16GB = {"total_ram_mb": 16000}


def test_dense_model_fits_vram():
    """A 2B dense model fits 6GB VRAM: no MoE offload, mlock on, VRAM-based ctx."""
    cfg = compute_launch_config(_NVIDIA_6GB, _CPU, _RAM_30GB, model_size_mb=3100, is_moe=False)
    assert cfg["is_moe"] is False
    assert cfg["n_cpu_moe"] == 0
    assert cfg["mlock"] is True            # fits in VRAM → lock pages
    assert cfg["recommended_n_gpu_layers"] == 999
    assert cfg["recommended_ctx_size"] <= 32768


def test_moe_model_offloads_experts():
    """A 26B MoE doesn't fit 6GB VRAM: offload experts to CPU, no mlock."""
    cfg = compute_launch_config(_NVIDIA_6GB, _CPU, _RAM_30GB, model_size_mb=16000, is_moe=True)
    assert cfg["is_moe"] is True
    assert cfg["n_cpu_moe"] == 999          # offload all expert layers
    assert cfg["mlock"] is False            # too big to lock
    assert cfg["recommended_ctx_size"] >= 8192


def test_moe_ctx_scales_down_on_tight_ram():
    """Same 26B on a 16GB-RAM box must NOT keep a huge ctx (would OOM)."""
    big = compute_launch_config(_NVIDIA_6GB, _CPU, _RAM_30GB, model_size_mb=16000, is_moe=True)
    small = compute_launch_config(_NVIDIA_6GB, _CPU, _RAM_16GB, model_size_mb=16000, is_moe=True)
    assert small["recommended_ctx_size"] <= big["recommended_ctx_size"]


def test_dense_model_does_not_get_moe_flag():
    """A large dense model must still never get --n-cpu-moe."""
    cfg = compute_launch_config(_NVIDIA_6GB, _CPU, _RAM_30GB, model_size_mb=16000, is_moe=False)
    assert cfg["n_cpu_moe"] == 0


def test_cpu_only_no_gpu_offload():
    """No GPU: no layer offload, no MoE CPU flag (everything is already CPU)."""
    cpu_gpu = {"detected": False, "vendor": "none", "vram_mb": 0}
    cfg = compute_launch_config(cpu_gpu, _CPU, _RAM_30GB, model_size_mb=16000, is_moe=True)
    assert cfg["recommended_n_gpu_layers"] == 0
    assert cfg["n_cpu_moe"] == 0
