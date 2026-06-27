"""
Service manager for Atri Code CLI.

Automatically starts llama-server and orchestrator when the CLI launches.
In production mode, services are persistent daemons that stay "warm" 
between CLI sessions for sub-second responsiveness.

Handles:
- Service health checking
- Persistent daemon management (detached lifecycle)
- Port conflict detection
- Manual shutdown via 'atri-cli stop'
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

try:
    import resource  # POSIX only; gate --mlock on the RLIMIT_MEMLOCK ceiling
except ImportError:  # pragma: no cover - non-POSIX
    resource = None  # type: ignore


def _memlock_allows(size_bytes: int) -> bool:
    """True if RLIMIT_MEMLOCK can actually lock `size_bytes` in RAM.

    Most Linux desktops cap memlock at systemd's DefaultLimitMEMLOCK (8 MB), which
    makes ``--mlock`` on a multi-GB model fail (locks 0 bytes — only a warning) and
    wastes the attempt. Only pass ``--mlock`` when the soft limit can hold the model;
    otherwise the model stays pageable (and the user can raise the limit via
    /etc/security/limits.d to get guaranteed locking).
    """
    if resource is None or size_bytes <= 0:
        return resource is not None
    try:
        soft, _hard = resource.getrlimit(resource.RLIMIT_MEMLOCK)
    except (ValueError, OSError):
        return True
    if soft == resource.RLIM_INFINITY:
        return True
    return soft >= int(size_bytes * 0.95)


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains runtime/ and services/)."""
    # This file is at: <repo>/apps/cli/atri_cli/service_manager.py
    candidate = Path(__file__).resolve().parents[3]
    if (candidate / "runtime").is_dir() and (candidate / "services").is_dir():
        return candidate

    # Fallback: check common install locations
    install_root_env = os.environ.get("ATRI_INSTALL_ROOT", "")
    fallback_candidates = [
        Path(install_root_env) / "src" if install_root_env else None,
        Path.home() / ".local/share/atri/src",
        Path.home() / ".local/share/atri-code",
        Path.home() / "Agentic_AI",
        Path.cwd(),
    ]
    for path in fallback_candidates:
        if path is None:
            continue
        if path.is_dir() and (path / "runtime").is_dir():
            return path

    # Last resort: use env var
    env_dir = os.environ.get("ATRI_REPO_DIR", "")
    if env_dir:
        return Path(env_dir).resolve()

    return candidate  # Best guess


def _check_health(url: str, timeout: float = 2.0) -> bool:
    """Check if a service is responding."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "atri-cli/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def _wait_for_health(url: str, timeout_sec: int = 90, label: str = "") -> bool:
    """Wait for a service to become healthy."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if _check_health(url):
            return True
        time.sleep(0.5)
    return False


def _is_port_in_use(port: int) -> bool:
    """Check if a port is already in use."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


class ServiceManager:
    """Manages llama-server and orchestrator lifecycle."""

    def __init__(self, repo_root: Optional[Path] = None):
        self.repo_root = repo_root or _find_repo_root()
        self._llama_proc: Optional[subprocess.Popen] = None
        self._orch_proc: Optional[subprocess.Popen] = None
        self._owns_llama = False
        self._owns_orch = False

        # Ports
        self.llama_port = int(os.environ.get("ATRI_LLAMA_PORT", "8000"))
        self.orch_port = int(os.environ.get("ATRI_ORCH_PORT", "8001"))

        self.llama_health_url = f"http://127.0.0.1:{self.llama_port}/health"
        self.orch_health_url = f"http://127.0.0.1:{self.orch_port}/health"

    @property
    def llama_running(self) -> bool:
        return _check_health(self.llama_health_url)

    @property
    def orch_running(self) -> bool:
        return _check_health(self.orch_health_url)

    def _get_launch_config(self) -> dict:
        """Load (or regenerate) launch_config.json for the CURRENT model.

        The config is model-specific (n_cpu_moe, ctx, mlock differ for a dense
        2B vs a 26B MoE). A cached config is reused only if it was computed for
        the model we're about to serve; otherwise it's regenerated. This is what
        makes the launcher model-agnostic — switching models picks up the right
        optimisation flags instead of reusing the previous model's config.
        """
        config_path = self.repo_root / "runtime" / "llm" / "launch_config.json"
        model = self._find_model()
        model_path = str(model) if model else ""

        cached: Optional[dict] = None
        if config_path.exists():
            try:
                cached = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                cached = None
        if cached is not None and model_path and cached.get("model_path", "") == model_path:
            return cached

        # Model changed (or no cached config): regenerate for the current model.
        detect_script = self.repo_root / "scripts" / "detect_hardware.py"
        if detect_script.exists():
            try:
                env = os.environ.copy()
                if model_path:
                    env["ATRI_MODEL_PATH"] = model_path
                subprocess.run(
                    [sys.executable, str(detect_script), "--save"],
                    capture_output=True, text=True, timeout=30, check=True,
                    cwd=str(self.repo_root), env=env,
                )
                if config_path.exists():
                    return json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        if cached is not None:
            return cached  # last resort: stale config beats nothing

        # Conservative defaults used when detect_hardware.py hasn't run yet.
        # detect_hardware.py writes launch_config.json with device-specific values.
        return {
            "recommended_n_gpu_layers": 99,
            "recommended_ctx_size": 16384,
            "recommended_batch_size": 2048,
            "recommended_ubatch_size": 512,
            "recommended_threads": max(2, (os.cpu_count() or 4) - 2),
            "flash_attn": False,
            "kv_cache_type_k": "q8_0",
            "kv_cache_type_v": "q8_0",
            "mlock": False,
            "gpu_detected": False,
        }

    def _find_llama_binary(self) -> Optional[Path]:
        """Find the llama-server binary.

        Search order:
        1. $LLAMA_SERVER_BIN env (set by the smart installer launcher script)
        2. New install layout: ~/.local/share/atri/runtime/llama/llama-server
        3. Legacy dev layout: runtime/llm/llama.cpp/build/bin/llama-server
        """
        from_env = os.environ.get("LLAMA_SERVER_BIN")
        if from_env:
            p = Path(from_env)
            if p.exists():
                return p

        install_root = Path(os.environ.get("ATRI_INSTALL_ROOT", Path.home() / ".local/share/atri"))
        candidates = [
            install_root / "runtime/llama/llama-server",
            install_root / "runtime/llama/llama-server.exe",
            self.repo_root / "runtime/llm/llama.cpp/build/bin/llama-server",
            self.repo_root / "runtime/llm/llama.cpp/build/bin/Release/llama-server.exe",
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    def _find_model(self) -> Optional[Path]:
        """Find the main GGUF model file."""
        # Honour explicit path set by installer launcher
        explicit = os.environ.get("ATRI_MODEL_PATH", "")
        if explicit and Path(explicit).exists():
            return Path(explicit)

        install_root = Path(os.environ.get("ATRI_INSTALL_ROOT", Path.home() / ".local/share/atri"))
        model_dirs = [
            Path(os.environ.get("ATRI_MODEL_DIR", str(install_root / "models"))),
            self.repo_root / "models",
        ]

        # Default target is the text-only Gemma 4 E2B decoder: it fits entirely
        # in modest VRAM (e.g. 6 GB RTX 3060) for fast, reliable responses.
        # The larger 26B MoE is opt-in via ATRI_MODEL_PATH / ATRI_MODEL_DIR.
        preferred = [
            "gemma-4-E2B-it-Q4_K_M.gguf",
            "gemma-4-e2b-it-Q4_K_M.gguf",
            "gemma-4-26B-A4B-it-UD-Q4_K_M.gguf",
        ]
        for mdir in model_dirs:
            for name in preferred:
                p = mdir / name
                if p.exists():
                    return p
            # Fall back to any gguf that isn't the vision projector
            for gguf in sorted(mdir.glob("*.gguf")):
                if "mmproj" not in gguf.name.lower():
                    return gguf

        return None

    @staticmethod
    def _is_moe_model(model: Path) -> bool:
        """Heuristic: does this GGUF use Mixture-of-Experts layers?

        Only MoE models accept --n-cpu-moe; passing it to a dense model
        (e.g. the 2B E2B decoder) makes llama-server reject the flag.
        """
        name = model.name.lower()
        return any(tag in name for tag in ("moe", "a4b", "-26b", "-27b", "x7b", "8x"))

    def _find_mmproj(self, model: Optional[Path] = None) -> Optional[Path]:
        """Find the multimodal projector (mmproj) file.

        Searches, in order: ATRI_MMPROJ_PATH, the selected model's own directory
        (so a model on an external drive finds its sibling mmproj), then the
        standard model dirs. This keeps mmproj discovery model-location agnostic.
        """
        explicit = os.environ.get("ATRI_MMPROJ_PATH", "")
        if explicit and Path(explicit).exists():
            return Path(explicit)

        install_root = Path(os.environ.get("ATRI_INSTALL_ROOT", Path.home() / ".local/share/atri"))
        model_dirs: list[Path] = []
        if model is not None:
            model_dirs.append(model.parent)  # mmproj usually ships beside the model
        model_dirs.append(Path(os.environ.get("ATRI_MODEL_DIR", str(install_root / "models"))))
        model_dirs.append(self.repo_root / "models")

        for mdir in model_dirs:
            if not mdir.is_dir():
                continue
            p = mdir / "mmproj-BF16.gguf"
            if p.exists():
                return p
            for gguf in sorted(mdir.glob("mmproj*.gguf")):
                return gguf

        return None

    # ── PID file helpers ─────────────────────────────────────────────────────

    def _pid_file(self, service: str) -> Path:
        state = self.repo_root / "runtime" / "state"
        state.mkdir(parents=True, exist_ok=True)
        return state / f"{service}.pid"

    def _write_pid(self, service: str, pid: int) -> None:
        self._pid_file(service).write_text(str(pid), encoding="utf-8")

    def _kill_service(self, service: str) -> bool:
        """Kill a service by reading its PID file. Returns True if killed."""
        pid_file = self._pid_file(service)
        if not pid_file.exists():
            return False
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            # Wait up to 5s for the process to exit
            deadline = time.time() + 5
            while time.time() < deadline:
                try:
                    os.kill(pid, 0)  # check if still alive
                    time.sleep(0.2)
                except ProcessLookupError:
                    break
            else:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            pid_file.unlink(missing_ok=True)
            return True
        except (ValueError, ProcessLookupError, PermissionError):
            pid_file.unlink(missing_ok=True)
            return False

    def _find_python(self) -> str:
        """Find the orchestrator venv python."""
        # Check dev layout: services/orchestrator/.venv
        venv_py = self.repo_root / "services/orchestrator/.venv/bin/python"
        if venv_py.exists():
            return str(venv_py)
        # Check installed layout: ~/.local/share/atri/venv
        install_root = Path(os.environ.get("ATRI_INSTALL_ROOT", Path.home() / ".local/share/atri"))
        installed_py = install_root / "venv/bin/python"
        if installed_py.exists():
            return str(installed_py)
        return sys.executable

    def _write_env_if_missing(self) -> None:
        """Generate .env for orchestrator if missing."""
        env_file = self.repo_root / "services/orchestrator/.env"
        if env_file.exists():
            return
        db_state = (self.repo_root / "runtime" / "state").resolve()
        db_state.mkdir(parents=True, exist_ok=True)
        env_file.write_text(
            "\n".join([
                f"LLM_BASE_URL=http://127.0.0.1:{self.llama_port}/v1",
                "LLM_API_KEY=secret",
                "LLM_MODEL=local-model",
                "LLM_TEMPERATURE=0.6",
                "LLM_MAX_TOKENS=4096",
                "LLM_TIMEOUT_SECONDS=300",
                "MCP_DEFAULT_TRANSPORT=stdio",
                "MCP_TOOL_TIMEOUT_SECONDS=15",
                "MCP_ALLOW_HIDDEN=true",
                "AGENT_MAX_TURNS=10",
                "AGENT_MAX_TOOL_CALLS_PER_TURN=3",
                "AGENT_ENABLE_TOOL_USE=true",
                "AGENT_THINKING_MODE=tool_calls_off",
                "AGENT_STREAM_RESPONSES=false",
                f"ORCHESTRATOR_DATABASE_URL=sqlite:///{db_state}/orchestrator.db",
                "ORCHESTRATOR_ENABLE_PERSISTENCE=true",
                "ORCHESTRATOR_AUTH_MODE=hybrid",
                "ORCHESTRATOR_JWT_SECRET=",
                "ORCHESTRATOR_API_KEY=",
                "ORCHESTRATOR_ADMIN_API_KEY=",
                "LOG_LEVEL=INFO",
                "ENABLE_OBSERVABILITY=true",
                "PROMPT_POLICY_DEFAULT_PROFILE=agent-v3",
            ]) + "\n",
            encoding="utf-8",
        )

    def start_llama(self, tui=None) -> bool:
        """Start llama-server if not already running."""
        if self.llama_running:
            return True

        llama_bin = self._find_llama_binary()
        if not llama_bin:
            if tui:
                tui.render_error(
                    "llama-server binary not found. Run the installer first:\n"
                    "  curl -fsSL https://raw.githubusercontent.com/ToniBirat7/Agentic_AI/master/install.sh | bash"
                )
            return False

        model = self._find_model()
        if not model:
            if tui:
                tui.render_error(
                    "No model file found. Run the installer and provide the path to\n"
                    "gemma-4-26B-A4B-it-UD-Q4_K_M.gguf, or set ATRI_MODEL_PATH."
                )
            return False

        is_moe = self._is_moe_model(model)
        # Vision projector only matters for the multimodal MoE build; the
        # text-only E2B decoder runs without it. Search beside the model too.
        mmproj = self._find_mmproj(model) if is_moe else None

        config = self._get_launch_config()

        n_gpu = str(config.get("recommended_n_gpu_layers", 999))
        ctx = str(config.get("recommended_ctx_size", 32768))
        raw_threads = config.get("recommended_threads", max(2, (os.cpu_count() or 4) - 2))
        threads = str(min(6, int(raw_threads)) if config.get("gpu_detected") else int(raw_threads))
        batch = str(config.get("recommended_batch_size", 2048))
        ubatch = str(config.get("recommended_ubatch_size", 512))
        flash = config.get("flash_attn", True)
        kv_k = config.get("kv_cache_type_k", "q4_0")
        kv_v = config.get("kv_cache_type_v", "q8_0")

        # Gemma 4 chat template — try install-root first, then repo fallback
        install_root = Path(os.environ.get("ATRI_INSTALL_ROOT", Path.home() / ".local/share/atri"))
        template_file = Path(os.environ.get("ATRI_TEMPLATE_DIR", str(install_root / "runtime/templates"))) / "gemma4-tooluse.jinja"
        if not template_file.exists():
            template_file = self.repo_root / "runtime" / "templates" / "gemma4-tooluse.jinja"

        cmd = [
            str(llama_bin),
            "-m", str(model),
        ]
        if mmproj:
            cmd.extend(["--mmproj", str(mmproj)])
        cmd.extend([
            "--jinja",
            "--host", "127.0.0.1",
            "--port", str(self.llama_port),
            "--threads", threads,
            "--n-gpu-layers", n_gpu,
            "--ctx-size", ctx,
            "--batch-size", batch,
            "--ubatch-size", ubatch,
            "--cache-type-k", kv_k,
            "--cache-type-v", kv_v,
            "--parallel", "1",
            "--no-mmap",
            "--api-key", "secret",
        ])
        if template_file.exists():
            cmd.extend(["--chat-template-file", str(template_file)])
        if flash:
            cmd.extend(["--flash-attn", "on"])
        if config.get("mlock", True):
            try:
                model_bytes = model.stat().st_size
            except OSError:
                model_bytes = 0
            # Only lock if the OS memlock ceiling can hold the model — otherwise
            # --mlock fails with a warning and changes nothing (see _memlock_allows).
            if _memlock_allows(model_bytes):
                cmd.append("--mlock")
        n_cpu_moe = config.get("n_cpu_moe", 0)
        if is_moe and n_cpu_moe > 0:
            cmd.extend(["--n-cpu-moe", str(n_cpu_moe)])

        log_path = self.repo_root / "llama.log"
        log_fp = open(log_path, "ab")

        # Ensure shared libs co-located with the binary are found (e.g. libmtmd.so.0)
        lib_dir = str(llama_bin.parent)
        env = os.environ.copy()
        existing_ld = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{lib_dir}:{existing_ld}" if existing_ld else lib_dir
        env["GGML_CUDA_ENABLE_UNIFIED_MEMORY"] = "1"

        proc = subprocess.Popen(
            cmd,
            cwd=str(llama_bin.parent),
            env=env,
            stdout=log_fp,
            stderr=log_fp,
            start_new_session=True,
            close_fds=True,
        )
        self._write_pid("llama-server", proc.pid)
        self._owns_llama = True
        return True

    def start_orchestrator(self, tui=None) -> bool:
        """Start orchestrator if not already running."""
        if self.orch_running:
            return True

        # Ensure runtime/state dir exists (SQLite DB lives here)
        (self.repo_root / "runtime" / "state").mkdir(parents=True, exist_ok=True)

        self._write_env_if_missing()
        py = self._find_python()

        orch_dir = self.repo_root / "services/orchestrator"
        # Check for api.py or the compiled version in __pycache__ or parent
        api_py = orch_dir / "api.py"
        if not api_py.exists() and not list(orch_dir.glob("**/api*.pyc")):
            if tui:
                tui.render_error("Orchestrator entry point not found. Please run 'atri-cli upgrade'.")
            return False

        log_path = self.repo_root / "orchestrator.log"
        log_fp = open(log_path, "ab")

        # Strip auth vars that may have leaked in from a previous dev shell.
        # If a stale ORCHESTRATOR_API_KEY/JWT_SECRET is inherited here, the
        # daemon would require auth the (anonymous) CLI never sends -> HTTP 401.
        # Removing them lets the orchestrator's .env (blank by default) be the
        # single source of truth via load_dotenv(override=False).
        env = os.environ.copy()
        for leaked in (
            "ORCHESTRATOR_API_KEY",
            "ORCHESTRATOR_ADMIN_API_KEY",
            "ORCHESTRATOR_JWT_SECRET",
        ):
            env.pop(leaked, None)

        # Auto-select the prompt profile to match the model that start_llama
        # serves: the richer agent-v3-26b for the MoE build, the leaner agent-v3
        # (tuned for the 2B E2B decoder) otherwise. Set as a real env var so it
        # wins over a stale .env value (config uses load_dotenv override=False).
        model = self._find_model()
        if model is not None:
            env["PROMPT_POLICY_DEFAULT_PROFILE"] = (
                "agent-v3-26b" if self._is_moe_model(model) else "agent-v3"
            )

        proc = subprocess.Popen(
            [py, "-m", "uvicorn", "api:app", "--host", "127.0.0.1", "--port", str(self.orch_port)],
            cwd=str(orch_dir),
            env=env,
            stdout=log_fp,
            stderr=log_fp,
            start_new_session=True,
            close_fds=True,
        )
        self._write_pid("orchestrator", proc.pid)
        self._owns_orch = True
        return True

    def ensure_services(self, tui=None) -> bool:
        """
        Ensure both services are running. Auto-starts them if needed.
        Shows Rich spinner while waiting.
        Returns True if both healthy.
        """
        llama_was_running = self.llama_running
        orch_was_running = self.orch_running

        if llama_was_running and orch_was_running:
            return True

        # Start services that need starting
        if not llama_was_running:
            if tui:
                tui.start_thinking()
                tui.update_thinking("Starting llama-server...")
            if not self.start_llama(tui):
                if tui:
                    tui.stop_thinking()
                return False

        if not orch_was_running:
            if tui:
                tui.update_thinking("Starting orchestrator...")
            if not self.start_orchestrator(tui):
                if tui:
                    tui.stop_thinking()
                return False

        # Wait for health
        if tui:
            tui.update_thinking("Waiting for llama-server...")

        if not llama_was_running:
            llama_ok = _wait_for_health(
                self.llama_health_url,
                timeout_sec=360,
                label="llama-server",
            )
            if not llama_ok:
                if tui:
                    tui.stop_thinking()
                    tui.render_error(
                        "llama-server failed to start within 360s.\n"
                        "Check llama.log for details."
                    )
                return False

        if tui:
            tui.update_thinking("Waiting for orchestrator...")

        if not orch_was_running:
            orch_ok = _wait_for_health(
                self.orch_health_url,
                timeout_sec=60,
                label="orchestrator",
            )
            if not orch_ok:
                if tui:
                    tui.stop_thinking()
                    tui.render_error(
                        "Orchestrator failed to start within 60s.\n"
                        "Check orchestrator.log for details."
                    )
                return False

        if tui:
            tui.stop_thinking()
            if not llama_was_running or not orch_was_running:
                tui.render_success("Services started successfully")

        # Register cleanup
        # In production mode, we leave services running for persistence.
        # Use 'atri-cli stop' to explicitly shut them down.
        return True

    def shutdown(self) -> None:
        """Gracefully stop services by PID file. Works even after CLI restart."""
        for service in ("orchestrator", "llama-server"):
            killed = self._kill_service(service)
            if killed:
                print(f"  Stopped {service}")

    def status(self) -> dict:
        """Return status of all services + the active model and its optimisation."""
        config = self._get_launch_config()
        model = self._find_model()
        return {
            "llama_server": {
                "running": self.llama_running,
                "url": f"http://127.0.0.1:{self.llama_port}",
                "owns": self._owns_llama,
            },
            "orchestrator": {
                "running": self.orch_running,
                "url": f"http://127.0.0.1:{self.orch_port}",
                "owns": self._owns_orch,
            },
            "model": model.name if model else None,
            "is_moe": config.get("is_moe", False),
            "n_cpu_moe": config.get("n_cpu_moe", 0),
            "mlock": config.get("mlock", False),
            "gpu": config.get("gpu_name", ""),
            "ctx_size": config.get("recommended_ctx_size", 0),
            "flash_attn": config.get("flash_attn", False),
            "reasoning": config.get("enable_thinking", True),
        }
