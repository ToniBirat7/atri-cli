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


def _python_bin(repo_dir: Path) -> Path:
    if os.name == "nt":
        return repo_dir / "services/orchestrator/.venv/Scripts/python.exe"
    return repo_dir / "services/orchestrator/.venv/bin/python"


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
        temp_path.replace(model_path)
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
        _run(["git", "clone", "--single-branch", "--branch", branch, repo_url, str(repo_dir)])

    print(f"[local-up] Syncing branch '{branch}'")
    _run(["git", "fetch", "origin"], cwd=repo_dir)
    _run(["git", "checkout", branch], cwd=repo_dir)
    _run(["git", "pull", "--ff-only", "origin", branch], cwd=repo_dir)


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

    mcp_reqs = repo_dir / "services/mcp/requirements.txt"
    if mcp_reqs.exists():
        print("[local-up] Installing MCP dependencies...")
        _run([str(py), "-m", "pip", "install", "-r", str(mcp_reqs)], cwd=repo_dir)


def _build_llama(repo_dir: Path, use_gpu: bool) -> None:
    print("[local-up] Building llama.cpp...")
    cmake_cmd = [
        "cmake",
        "-S",
        ".",
        "-B",
        "build",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DBUILD_SHARED_LIBS=ON",
        "-DGGML_NATIVE=ON",
    ]

    if use_gpu:
        print("[local-up] GPU detected; using CUDA build")
        cmake_cmd.extend(["-DGGML_CUDA=ON"])
    else:
        print("[local-up] GPU not detected; using CPU-optimized build")
        cmake_cmd.extend(["-DGGML_CUDA=OFF", "-DGGML_OPENMP=ON"])

    llama_dir = repo_dir / "runtime/llm/llama.cpp"
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


def _write_orchestrator_env(repo_dir: Path) -> None:
    env_file = repo_dir / "services/orchestrator/.env"
    if env_file.exists():
        return

    env_file.write_text(
        "\n".join(
            [
                "LLM_BASE_URL=http://127.0.0.1:8000/v1",
                "LLM_API_KEY=__SET_ME__",
                "LLM_MODEL=local-model",
                "MCP_DEFAULT_TRANSPORT=stdio",
                "MCP_TOOL_TIMEOUT_SECONDS=10",
                "AGENT_MAX_TURNS=10",
                "AGENT_MAX_TOOL_CALLS_PER_TURN=3",
                "AGENT_ENABLE_TOOL_USE=true",
                "AGENT_ENABLE_THINKING=false",
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


def _start_services_by_mode(repo_dir: Path, use_gpu: bool, mode: str) -> None:
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
    n_gpu_layers = "999" if use_gpu else "0"

    print("[local-up] Starting llama server...")
    _spawn(
        [
            str(llama_bin),
            "-m",
            str(model_path),
            "--jinja",
            "--chat-template-kwargs",
            '{"enable_thinking":false}',
            "--port",
            "8000",
            "--threads",
            "12",
            "--n-gpu-layers",
            n_gpu_layers,
            "--ctx-size",
            "16384",
            "--api-key",
            "secret",
        ],
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

    llama_ok = _wait_health("http://127.0.0.1:8000/health", timeout_sec=90)
    orch_ok = _wait_health("http://127.0.0.1:8001/health", timeout_sec=60)
    orch_ready = _wait_health("http://127.0.0.1:8001/ready", timeout_sec=60)

    print("\n[local-up] Startup summary:")
    print(f"  mode: {mode}")
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
    _ensure_model(repo_dir)
    use_gpu = _detect_gpu()
    _build_llama(repo_dir, use_gpu)
    _start_services_by_mode(repo_dir, use_gpu, args.mode)

    if not args.no_production_prune:
        _prune_non_production(repo_dir)

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
