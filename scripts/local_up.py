#!/usr/bin/env python3
"""Branch-aware local bootstrap for Atri Code with production cleanup.

This script can:
- clone/update a specific branch
- install dependencies and build llama.cpp
- prune non-production files from the local install directory
- clean project and package-manager caches
- start services for full, cli, or web mode
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


DEFAULT_REPO_URL = "https://github.com/ToniBirat7/Agentic_AI.git"
DEFAULT_REPO_DIR = "Agentic_AI"
DEFAULT_BRANCH = "master"
MODEL_REL_PATH = Path("models/gemma-4-e2b-it-Q4_K_M.gguf")
MODEL_DOWNLOAD_URL = (
    "https://huggingface.co/unsloth/gemma-4-E2B-it-GGUF/resolve/main/"
    "gemma-4-E2B-it-Q4_K_M.gguf?download=true"
)

PRIMARY_LAUNCHER = "atri"
COMPAT_LAUNCHER = "atri-cli"
ALIAS_LAUNCHER = "tarbar"


def _run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and proc.returncode != 0:
        joined = " ".join(cmd)
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        message = stderr or stdout or "command failed"
        raise RuntimeError(f"Command failed ({proc.returncode}): {joined}\n{message}")
    return proc


def _which_or_fail(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Missing required command: {name}")


def _find_cuda_compatible_gcc() -> str | None:
    """Return path to a GCC <=14 for use as CUDA host compiler, or None if system GCC is fine."""
    import re
    # Check system GCC version
    try:
        out = subprocess.run(["g++", "--version"], capture_output=True, text=True).stdout
        m = re.search(r"\(GCC\) (\d+)\.", out)
        if m and int(m.group(1)) <= 14:
            return None  # system GCC is compatible
    except Exception:
        return None
    # Try versioned GCC binaries from newest-compatible downward
    for ver in range(14, 9, -1):
        path = shutil.which(f"g++-{ver}")
        if path:
            return path
    return None


def _python_bin(repo_dir: Path) -> Path:
    if os.name == "nt":
        return repo_dir / "services/orchestrator/.venv/Scripts/python.exe"
    return repo_dir / "services/orchestrator/.venv/bin/python"


def _launcher_python(repo_dir: Path) -> str:
    py = _python_bin(repo_dir)
    if py.exists():
        return str(py)
    return "python3"


def _write_cli_launcher(bin_path: Path, repo_dir: Path) -> None:
    launcher = f"""#!/usr/bin/env sh
set -eu

REPO_DIR={str(repo_dir)!r}
PYTHON_BIN={_launcher_python(repo_dir)!r}

export PYTHONPATH=\"$REPO_DIR/apps/cli${{PYTHONPATH:+:$PYTHONPATH}}\"
exec \"$PYTHON_BIN\" -m atri_cli.main \"$@\"
"""
    bin_path.parent.mkdir(parents=True, exist_ok=True)
    bin_path.write_text(launcher, encoding="utf-8")
    current_mode = bin_path.stat().st_mode
    bin_path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _write_compat_launcher(bin_path: Path, primary_path: Path) -> None:
    launcher = f"""#!/usr/bin/env sh
echo "[deprecated] 'tarbar' is a compatibility alias. Use 'atri-cli' instead." >&2
exec {str(primary_path)!r} "$@"
"""
    bin_path.parent.mkdir(parents=True, exist_ok=True)
    bin_path.write_text(launcher, encoding="utf-8")
    current_mode = bin_path.stat().st_mode
    bin_path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _install_cli_launchers(repo_dir: Path) -> None:
    user_bin = Path.home() / ".local/bin"
    user_bin.mkdir(parents=True, exist_ok=True)
    
    py = _python_bin(repo_dir)
    print(f"[local-up] Installing CLI package via pip ({py})...")
    
    # Install the CLI package in the venv
    try:
        _run([str(py), "-m", "pip", "install", "-e", str(repo_dir / "apps/cli")], cwd=repo_dir)
        
        # Symlink the resulting entry point to ~/.local/bin
        venv_bin = py.parent / PRIMARY_LAUNCHER
        target_bin = user_bin / PRIMARY_LAUNCHER
        
        if venv_bin.exists():
            if target_bin.exists() or target_bin.is_symlink():
                target_bin.unlink()
            target_bin.symlink_to(venv_bin)
            print(f"[local-up] Symlinked global command: {target_bin} -> {venv_bin}")
        else:
            print(f"[local-up] Warning: venv entry point not found at {venv_bin}")
            _write_cli_launcher(target_bin, repo_dir)
            
    except Exception as e:
        print(f"[local-up] Warning: pip install failed ({e}), falling back to manual launcher")
        _write_cli_launcher(user_bin / PRIMARY_LAUNCHER, repo_dir)

    path_entries = os.environ.get("PATH", "").split(":")
    if str(user_bin) not in path_entries:
        print("[local-up] Installed launchers to ~/.local/bin, but it is not in PATH.")
        print("[local-up] Run: export PATH=\"$HOME/.local/bin:$PATH\"")

    print(f"[local-up] CLI launcher ready: {user_bin / PRIMARY_LAUNCHER}")
    print(f"[local-up] Start TUI with: {PRIMARY_LAUNCHER}")


def _llama_server_bin(repo_dir: Path) -> Path:
    candidates: list[Path] = []
    if os.name == "nt":
        candidates.extend(
            [
                repo_dir / "runtime/llm/llama.cpp/build/bin/llama-server.exe",
                repo_dir / "runtime/llm/llama.cpp/build/bin/Release/llama-server.exe",
            ]
        )
    else:
        candidates.append(repo_dir / "runtime/llm/llama.cpp/build/bin/llama-server")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _detect_gpu() -> bool:
    return shutil.which("nvidia-smi") is not None and shutil.which("nvcc") is not None


def _load_hardware_config(repo_dir: Path) -> dict:
    """Run detect_hardware.py and return the full hardware config."""
    script = repo_dir / "scripts" / "detect_hardware.py"
    if not script.exists():
        return {}
    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=30, check=True,
        )
        import json as _json
        return _json.loads(result.stdout)
    except Exception:
        return {}


def _save_launch_config(repo_dir: Path, hw: dict) -> None:
    """Save launch_config.json from hardware detection."""
    config = hw.get("launch_config", {})
    if not config:
        return
    config_path = repo_dir / "runtime" / "llm" / "launch_config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    import json as _json
    config_path.write_text(_json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"[local-up] Saved launch config: {config_path}")


def _download_model(model_path: Path) -> None:
    model_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = model_path.with_suffix(model_path.suffix + ".part")
    if temp_path.exists():
        temp_path.unlink()

    print(f"[local-up] Downloading model to {model_path}...")
    request = urllib.request.Request(
        MODEL_DOWNLOAD_URL,
        headers={"User-Agent": "atri-code/1.0"},
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response, open(temp_path, "wb") as output_file:
            shutil.copyfileobj(response, output_file)
        
        # Ensure the destination directory exists again just in case, though it was created above.
        # Use shutil.move for better cross-filesystem support if os.rename/Path.replace fails.
        shutil.move(str(temp_path), str(model_path))
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def _ensure_model(repo_dir: Path) -> Path:
    model_path = repo_dir / MODEL_REL_PATH
    if not model_path.exists():
        _download_model(model_path)
    return model_path


def _backup_existing_dir(repo_dir: Path) -> Path:
    suffix = int(time.time())
    backup_dir = repo_dir.with_name(f"{repo_dir.name}_backup_{suffix}")
    shutil.move(str(repo_dir), str(backup_dir))
    return backup_dir


def _prepare_clone_target(repo_dir: Path) -> None:
    if not repo_dir.exists():
        return

    git_dir = repo_dir / ".git"
    if git_dir.exists() and git_dir.is_dir():
        return

    # Keep user data safe by moving aside non-git content instead of deleting it.
    if any(repo_dir.iterdir()):
        backup_dir = _backup_existing_dir(repo_dir)
        print(f"[local-up] Existing non-git directory moved to: {backup_dir}")
        return

    repo_dir.rmdir()


def _ensure_repo(repo_url: str, repo_dir: Path, branch: str, skip_clone: bool) -> None:
    _which_or_fail("git")
    git_repo_exists = (repo_dir / ".git").exists()

    if skip_clone and not git_repo_exists:
        print(
            "[local-up] --skip-clone requested but target is not a git repository; "
            "falling back to clone mode."
        )
        skip_clone = False

    if skip_clone:
        pass
    elif git_repo_exists:
        print(f"[local-up] Using existing repo: {repo_dir}")
    else:
        _prepare_clone_target(repo_dir)
        print(f"[local-up] Cloning branch '{branch}' into: {repo_dir}")
        _run(["git", "clone", "--recurse-submodules", "--single-branch", "--branch", branch, repo_url, str(repo_dir)])

    print(f"[local-up] Syncing branch '{branch}'")
    _run(["git", "fetch", "origin"], cwd=repo_dir)
    _run(["git", "checkout", branch], cwd=repo_dir)
    _run(["git", "pull", "--ff-only", "origin", branch], cwd=repo_dir)
    _run(["git", "submodule", "update", "--init", "--recursive"], cwd=repo_dir)


def _install_dependencies(repo_dir: Path, mode: str) -> None:
    _which_or_fail("cmake")
    _which_or_fail("node")
    _which_or_fail("npm")

    if mode in {"full", "web"}:
        print("[local-up] Installing frontend dependencies...")
        _run(["npm", "install"], cwd=repo_dir / "apps/frontend")

    print("[local-up] Installing orchestrator dependencies...")
    _run([sys.executable, "-m", "venv", ".venv"], cwd=repo_dir / "services/orchestrator")
    py = _python_bin(repo_dir)
    _run([str(py), "-m", "pip", "install", "--upgrade", "pip"], cwd=repo_dir / "services/orchestrator")
    _run([str(py), "-m", "pip", "install", "-r", "requirements.txt"], cwd=repo_dir / "services/orchestrator")

    cli_reqs = repo_dir / "apps/cli/requirements.txt"
    if cli_reqs.exists():
        print("[local-up] Installing CLI dependencies...")
        _run([str(py), "-m", "pip", "install", "-r", str(cli_reqs)], cwd=repo_dir)

    mcp_reqs = repo_dir / "services/mcp/requirements.txt"
    if mcp_reqs.exists():
        print("[local-up] Installing MCP dependencies...")
        _run([str(py), "-m", "pip", "install", "-r", str(mcp_reqs)], cwd=repo_dir)


def _build_llama(repo_dir: Path, use_gpu: bool, hw_config: dict | None = None) -> None:
    print("[local-up] Building llama.cpp...")
    llama_dir = repo_dir / "runtime/llm/llama.cpp"

    # Use hardware-detected cmake args if available
    if hw_config and hw_config.get("cmake_args"):
        cmake_args = hw_config["cmake_args"]
        gpu_info = hw_config.get("gpu", {})
        vendor = gpu_info.get("vendor", "none")
        if vendor == "nvidia":
            arch = gpu_info.get("cuda_architecture", "")
            print(f"[local-up] NVIDIA GPU detected: {gpu_info.get('name', 'unknown')}")
            print(f"[local-up] CUDA architecture: SM {arch}, VRAM: {gpu_info.get('vram_mb', 0)} MB")
        elif vendor != "none":
            print(f"[local-up] {vendor.upper()} GPU detected: {gpu_info.get('name', 'unknown')}")
        else:
            print("[local-up] No GPU detected; building CPU-optimized binary")
    else:
        # Fallback to basic detection
        cmake_args = [
            "-DCMAKE_BUILD_TYPE=Release",
            "-DBUILD_SHARED_LIBS=OFF",
            "-DGGML_NATIVE=ON",
        ]
        if use_gpu:
            print("[local-up] GPU detected; using CUDA build")
            cmake_args.append("-DGGML_CUDA=ON")
        else:
            print("[local-up] No GPU detected; using CPU-optimized build")
            cmake_args.extend(["-DGGML_CUDA=OFF", "-DGGML_OPENMP=ON"])

    # CUDA host compiler compatibility: nvcc has a max supported GCC version.
    # If system GCC is too new (e.g. GCC 16 with CUDA 13.x), inject an older one.
    if any("-DGGML_CUDA=ON" in a for a in cmake_args):
        cuda_host = _find_cuda_compatible_gcc()
        if cuda_host:
            cmake_args.append(f"-DCMAKE_CUDA_HOST_COMPILER={cuda_host}")
            print(f"[local-up] Using CUDA host compiler: {cuda_host}")

    cmake_cmd = ["cmake", "-S", ".", "-B", "build"] + cmake_args
    _run(cmake_cmd, cwd=llama_dir)
    _run(
        [
            "cmake",
            "--build",
            "build",
            "--config",
            "Release",
            "-j",
            str(os.cpu_count() or 4),
            "--target",
            "llama-server",
            "llama-cli",
        ],
        cwd=llama_dir,
    )
    print("[local-up] llama.cpp build complete.")


def _write_orchestrator_env(repo_dir: Path) -> None:
    env_file = repo_dir / "services/orchestrator/.env"
    if env_file.exists():
        return

    env_file.write_text(
        "\n".join(
            [
                "LLM_BASE_URL=http://127.0.0.1:8000/v1",
                "LLM_API_KEY=secret",
                "LLM_MODEL=local-model",
                "LLM_TEMPERATURE=0.7",
                "LLM_MAX_TOKENS=4096",
                "LLM_TIMEOUT_SECONDS=120",
                "MCP_DEFAULT_TRANSPORT=stdio",
                "MCP_TOOL_TIMEOUT_SECONDS=15",
                "AGENT_MAX_TURNS=15",
                "AGENT_MAX_TOOL_CALLS_PER_TURN=5",
                "AGENT_ENABLE_TOOL_USE=true",
                "AGENT_ENABLE_THINKING=true",
                "AGENT_STREAM_RESPONSES=false",
                "ORCHESTRATOR_DATABASE_URL=sqlite:///runtime/state/orchestrator.db",
                "ORCHESTRATOR_ENABLE_PERSISTENCE=true",
                "LOG_LEVEL=INFO",
                "ENABLE_OBSERVABILITY=true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _remove_path(path: Path) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
    return True


def _compile_and_abstract(repo_dir: Path) -> None:
    """Byte-compile Python files and remove source to abstract the implementation."""
    print("[local-up] Abstracting implementation (compiling to bytecode)...")
    import compileall
    
    # Compile apps and services
    compileall.compile_dir(str(repo_dir / "apps"), force=True, quiet=1)
    compileall.compile_dir(str(repo_dir / "services"), force=True, quiet=1)
    
    # Remove .py files in those directories
    for py_file in list(repo_dir.glob("apps/**/*.py")) + list(repo_dir.glob("services/**/*.py")):
        if py_file.name != "__init__.py": # Keep __init__.py for package structure
             py_file.unlink()
             
    print("[local-up] Implementation abstracted.")


def _prune_non_production(repo_dir: Path) -> None:
    print("[local-up] Pruning non-production files...")

    remove_dirs = [
        repo_dir / "docs",
        repo_dir / "notes_images",
        repo_dir / "mcp",
        repo_dir / "scripts",
        repo_dir / "benchmarks",
        repo_dir / "benchmark_reports",
        repo_dir / ".github",
        repo_dir / ".idea",
        repo_dir / ".vscode",
    ]

    for path in remove_dirs:
        _remove_path(path)

    remove_files = [
        repo_dir / "resources.md",
        repo_dir / "notes.ipynb",
        repo_dir / ".dockerignore",
        repo_dir / ".env.example",
    ]
    for path in remove_files:
        _remove_path(path)

    for tmp_file in repo_dir.glob(".tmp_*"):
        _remove_path(tmp_file)

    for ipynb in repo_dir.glob("**/*.ipynb"):
        _remove_path(ipynb)

    for test_dir in repo_dir.glob("**/tests"):
        if test_dir.is_dir():
            _remove_path(test_dir)

    keep_markdown = {
        Path("README.md"),
        Path("QUICKSTART.md"),
        Path("LICENSE"),
        Path("LICENSE.md"),
    }
    for md in repo_dir.glob("**/*.md"):
        if md.relative_to(repo_dir) not in keep_markdown:
            _remove_path(md)
            
    # Remove git info to make it non-traceable as a repo
    _remove_path(repo_dir / ".git")
    _remove_path(repo_dir / ".gitignore")
    _remove_path(repo_dir / ".gitmodules")
    
    # Hide installer scripts from root
    internal_dir = repo_dir / ".internal"
    internal_dir.mkdir(exist_ok=True)
    if (repo_dir / "install.sh").exists():
        shutil.move(str(repo_dir / "install.sh"), str(internal_dir / "install.sh"))
    if (repo_dir / "scripts/local_up.py").exists():
        shutil.move(str(repo_dir / "scripts/local_up.py"), str(internal_dir / "local_up.py"))


def _clean_local_caches(repo_dir: Path) -> None:
    print("[local-up] Cleaning local caches/artifacts...")

    direct_targets = [
        repo_dir / ".pytest_cache",
        repo_dir / ".mypy_cache",
        repo_dir / ".ruff_cache",
        repo_dir / "llama.log",
        repo_dir / "orchestrator.log",
        repo_dir / "frontend.log",
        repo_dir / "apps/frontend/.next",
        repo_dir / "apps/frontend/.npm",
    ]
    for target in direct_targets:
        _remove_path(target)

    for pycache in repo_dir.glob("**/__pycache__"):
        if pycache.is_dir():
            _remove_path(pycache)

    for pyc in list(repo_dir.glob("**/*.pyc")) + list(repo_dir.glob("**/*.pyo")):
        _remove_path(pyc)
        
    # Secure runtime directory
    runtime_dir = repo_dir / "runtime"
    if runtime_dir.exists():
        print("[local-up] Securing runtime data (chmod 700)...")
        runtime_dir.chmod(0o700)
        for p in runtime_dir.rglob("*"):
            try:
                if p.is_dir():
                    p.chmod(0o700)
                else:
                    p.chmod(0o600)
            except Exception:
                pass


def _clean_system_caches(repo_dir: Path) -> None:
    print("[local-up] Cleaning package-manager caches...")
    py = _python_bin(repo_dir)
    _run([str(py), "-m", "pip", "cache", "purge"], check=False)
    _run(["npm", "cache", "clean", "--force"], check=False)


def _spawn(cmd: list[str], cwd: Path, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fp = open(log_path, "ab")
    kwargs = {
        "cwd": str(cwd),
        "stdout": log_fp,
        "stderr": log_fp,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)


def _wait_health(url: str, timeout_sec: int = 60) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if 200 <= resp.status < 300:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _start_services_by_mode(repo_dir: Path, use_gpu: bool, mode: str, hw_config: dict | None = None) -> None:
    model_path = repo_dir / MODEL_REL_PATH
    if not model_path.exists():
        raise RuntimeError(
            "Model file missing after download attempt: "
            f"{model_path}\n"
            f"Expected download source: {MODEL_DOWNLOAD_URL}"
        )

    _write_orchestrator_env(repo_dir)
    py = _python_bin(repo_dir)
    llama_bin = _llama_server_bin(repo_dir)

    # Load launch config from hardware detection
    launch = {}
    config_path = repo_dir / "runtime" / "llm" / "launch_config.json"
    if config_path.exists():
        import json as _json
        launch = _json.loads(config_path.read_text(encoding="utf-8"))
    elif hw_config:
        launch = hw_config.get("launch_config", {})

    n_gpu_layers = str(launch.get("recommended_n_gpu_layers", 999 if use_gpu else 0))
    ctx_size = str(launch.get("recommended_ctx_size", 8192))
    threads = str(launch.get("recommended_threads", max(2, (os.cpu_count() or 4) - 2)))
    batch_size = str(launch.get("recommended_batch_size", 2048 if use_gpu else 512))
    flash_attn = launch.get("flash_attn", False)
    kv_k = launch.get("kv_cache_type_k", "q8_0" if use_gpu else "f16")
    kv_v = launch.get("kv_cache_type_v", "q8_0" if use_gpu else "f16")

    llama_cmd = [
        str(llama_bin),
        "-m", str(model_path),
        "--jinja",
        "--reasoning", "on",
        "--host", "127.0.0.1",
        "--port", "8000",
        "--threads", threads,
        "--n-gpu-layers", n_gpu_layers,
        "--ctx-size", ctx_size,
        "--batch-size", batch_size,
        "--cache-type-k", kv_k,
        "--cache-type-v", kv_v,
        "--api-key", "secret",
    ]
    if flash_attn:
        llama_cmd.extend(["--flash-attn", "on"])

    print(f"[local-up] Starting llama server (ctx={ctx_size}, gpu_layers={n_gpu_layers}, flash_attn={flash_attn})...")
    _spawn(
        llama_cmd,
        cwd=repo_dir / "runtime/llm/llama.cpp",
        log_path=repo_dir / "llama.log",
    )

    print("[local-up] Starting orchestrator...")
    _spawn(
        [str(py), "-m", "uvicorn", "api:app", "--host", "127.0.0.1", "--port", "8001"],
        cwd=repo_dir / "services/orchestrator",
        log_path=repo_dir / "orchestrator.log",
    )

    if mode in {"full", "web"}:
        print("[local-up] Starting frontend...")
        _spawn(["npm", "run", "dev"], cwd=repo_dir / "apps/frontend", log_path=repo_dir / "frontend.log")

    llama_ok = _wait_health("http://127.0.0.1:8000/health", timeout_sec=120)
    orch_ok = _wait_health("http://127.0.0.1:8001/health", timeout_sec=60)
    orch_ready = _wait_health("http://127.0.0.1:8001/ready", timeout_sec=60)

    print("\n[local-up] Startup summary:")
    print(f"  mode: {mode}")
    print(f"  reasoning: enabled")
    print(f"  flash attention: {'enabled' if flash_attn else 'disabled'}")
    print(f"  context size: {ctx_size}")
    print(f"  llama health: {'ok' if llama_ok else 'failed'}")
    print(f"  orchestrator health: {'ok' if orch_ok else 'failed'}")
    print(f"  orchestrator readiness: {'ready' if orch_ready else 'failed'}")
    if mode in {"full", "web"}:
        print("  frontend: http://127.0.0.1:3000")

    if not orch_ready:
        raise RuntimeError("orchestrator readiness failed; check orchestrator.log for MCP startup errors")


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap Atri Code with production cleanup")
    parser.add_argument("--repo-url", default=os.environ.get("TARBAR_REPO_URL", DEFAULT_REPO_URL))
    parser.add_argument("--repo-dir", default=os.environ.get("TARBAR_REPO_DIR", DEFAULT_REPO_DIR))
    parser.add_argument("--branch", default=os.environ.get("TARBAR_BRANCH", DEFAULT_BRANCH))
    parser.add_argument("--skip-clone", action="store_true", help="Use existing repo-dir without clone")
    parser.add_argument("--mode", choices=["full", "cli", "web"], default="full")
    parser.add_argument("--no-production-prune", action="store_true", help="Do not remove non-production files")
    parser.add_argument("--no-cache-clean", action="store_true", help="Do not clean local/system caches")
    args = parser.parse_args()

    repo_dir = Path(args.repo_dir).expanduser().resolve()

    _ensure_repo(args.repo_url, repo_dir, args.branch, args.skip_clone)
    _install_dependencies(repo_dir, args.mode)
    _install_cli_launchers(repo_dir)
    _ensure_model(repo_dir)

    # Hardware detection for optimized build
    hw_config = _load_hardware_config(repo_dir)
    use_gpu = _detect_gpu()
    if hw_config:
        _save_launch_config(repo_dir, hw_config)
    _build_llama(repo_dir, use_gpu, hw_config=hw_config)
    _start_services_by_mode(repo_dir, use_gpu, args.mode, hw_config=hw_config)

    if not args.no_production_prune:
        _prune_non_production(repo_dir)
        _compile_and_abstract(repo_dir)

    if not args.no_cache_clean:
        _clean_local_caches(repo_dir)
        _clean_system_caches(repo_dir)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[local-up] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
