#!/usr/bin/env python3
"""Bootstrap and start full local Tarbar_AI pipeline.

Cross-platform launcher for Linux and Windows:
- Clones or updates repository
- Installs dependencies
- Builds llama.cpp with GPU preference (CPU fallback)
- Starts llama server, orchestrator API, and frontend dev server
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
MODEL_REL_PATH = Path("models/gemma-4-e2b-it-Q4_K_M.gguf")


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")


def _which_or_fail(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Missing required command: {name}")


def _ensure_repo(repo_url: str, repo_dir: Path) -> None:
    _which_or_fail("git")
    if (repo_dir / ".git").exists():
        print(f"[local-up] Using existing repo: {repo_dir}")
        _run(["git", "fetch", "origin"], cwd=repo_dir)
        _run(["git", "pull", "--ff-only"], cwd=repo_dir)
        return

    if repo_dir.exists() and not any(repo_dir.iterdir()):
        repo_dir.rmdir()

    print(f"[local-up] Cloning repo into: {repo_dir}")
    _run(["git", "clone", repo_url, str(repo_dir)])


def _python_bin(repo_dir: Path) -> Path:
    if os.name == "nt":
        return repo_dir / "services/orchestrator/.venv/Scripts/python.exe"
    return repo_dir / "services/orchestrator/.venv/bin/python"


def _llama_server_bin(repo_dir: Path) -> Path:
    candidates = []
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


def _install_dependencies(repo_dir: Path) -> None:
    _which_or_fail("cmake")
    _which_or_fail("npm")
    _which_or_fail("node")

    print("[local-up] Installing frontend dependencies...")
    _run(["npm", "install"], cwd=repo_dir / "apps/frontend")

    print("[local-up] Creating orchestrator venv and installing dependencies...")
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
        cmake_cmd.extend(["-DGGML_CUDA=ON"])
        print("[local-up] GPU detected: using CUDA build")
    else:
        cmake_cmd.extend(["-DGGML_CUDA=OFF", "-DGGML_OPENMP=ON"])
        print("[local-up] GPU not detected: using CPU-optimized build")

    llama_dir = repo_dir / "runtime/llm/llama.cpp"
    _run(cmake_cmd, cwd=llama_dir)
    _run(["cmake", "--build", "build", "--config", "Release", "-j", str(os.cpu_count() or 4), "--target", "llama-server", "llama-cli"], cwd=llama_dir)


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
                "LLM_TEMPERATURE=1.0",
                "LLM_TOP_P=0.95",
                "LLM_TOP_K=64",
                "LLM_MAX_TOKENS=2048",
                "LLM_TIMEOUT_SECONDS=30",
                "LLM_PARALLEL_TOOL_CALLS=true",
                "MCP_DEFAULT_TRANSPORT=stdio",
                "MCP_TOOL_TIMEOUT_SECONDS=10",
                "MCP_MAX_TOOL_CALL_RETRIES=2",
                "AGENT_MAX_TURNS=10",
                "AGENT_MAX_TOOL_CALLS_PER_TURN=3",
                "AGENT_ENABLE_TOOL_USE=true",
                "AGENT_ENABLE_THINKING=false",
                "AGENT_STREAM_RESPONSES=false",
                "LOG_LEVEL=INFO",
                "ENABLE_OBSERVABILITY=true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


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


def _start_services(repo_dir: Path, use_gpu: bool) -> None:
    model_path = repo_dir / MODEL_REL_PATH
    if not model_path.exists():
        raise RuntimeError(
            "Model file missing: "
            f"{model_path}\n"
            "Download from: https://huggingface.co/lmstudio-ai/gemma-4-e2b-it-GGUF"
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

    print("[local-up] Starting frontend...")
    _spawn(["npm", "run", "dev"], cwd=repo_dir / "apps/frontend", log_path=repo_dir / "frontend.log")

    llama_ok = _wait_health("http://127.0.0.1:8000/health", timeout_sec=90)
    orch_ok = _wait_health("http://127.0.0.1:8001/health", timeout_sec=60)

    print("\n[local-up] Startup summary:")
    print(f"  llama health: {'ok' if llama_ok else 'failed'}")
    print(f"  orchestrator health: {'ok' if orch_ok else 'failed'}")
    print("  frontend: http://127.0.0.1:3000")
    print("\n[local-up] Run CLI:")
    print("  cd apps/cli")
    print("  PYTHONPATH=. ../../.env/bin/python -m tarbar_cli.main --api-url http://127.0.0.1:8001")


def _start_services_by_mode(repo_dir: Path, use_gpu: bool, mode: str) -> None:
    if mode == "full":
        _start_services(repo_dir, use_gpu)
        return

    model_path = repo_dir / MODEL_REL_PATH
    if not model_path.exists():
        raise RuntimeError(
            "Model file missing: "
            f"{model_path}\n"
            "Download from: https://huggingface.co/lmstudio-ai/gemma-4-e2b-it-GGUF"
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

    print("\n[local-up] Startup summary:")
    print(f"  mode: {mode}")
    print(f"  llama health: {'ok' if llama_ok else 'failed'}")
    print(f"  orchestrator health: {'ok' if orch_ok else 'failed'}")
    if mode in {"full", "web"}:
        print("  frontend: http://127.0.0.1:3000")
    if mode in {"full", "cli"}:
        print("\n[local-up] Run CLI:")
        print("  cd apps/cli")
        print("  PYTHONPATH=. ../../.env/bin/python -m tarbar_cli.main --api-url http://127.0.0.1:8001")


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap and start full local Tarbar_AI pipeline")
    parser.add_argument("--repo-url", default=os.environ.get("TARBAR_REPO_URL", DEFAULT_REPO_URL))
    parser.add_argument("--repo-dir", default=os.environ.get("TARBAR_REPO_DIR", DEFAULT_REPO_DIR))
    parser.add_argument("--skip-clone", action="store_true", help="Use existing repo-dir without clone/pull")
    parser.add_argument("--mode", choices=["full", "cli", "web"], default="full")
    args = parser.parse_args()

    repo_dir = Path(args.repo_dir).expanduser().resolve()
    if args.skip_clone:
        if not (repo_dir / ".git").exists():
            raise RuntimeError(f"Not a git repository: {repo_dir}")
    else:
        _ensure_repo(args.repo_url, repo_dir)

    _install_dependencies(repo_dir)
    use_gpu = _detect_gpu()
    _build_llama(repo_dir, use_gpu=use_gpu)
    _start_services_by_mode(repo_dir, use_gpu=use_gpu, mode=args.mode)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[local-up] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
