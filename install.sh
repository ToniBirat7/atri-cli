#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Atri Code — Smart one-command installer
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/ToniBirat7/Agentic_AI/master/install.sh | bash
#
# What it does:
#   1. Detects OS / architecture / GPU accelerator (CUDA / ROCm / Metal / CPU)
#   2. Downloads the matching llama-server prebuilt binary (NVIDIA/macOS/CPU)
#      or falls back to building from source for exotic targets
#   3. Installs the orchestrator + CLI Python packages into a venv
#   4. Lazy-fetches the Gemma 4 E2B Q4_K_M model on first run
#   5. Writes ~/.local/share/atri/ with a clean, minimal footprint
#   6. Symlinks `atri` into ~/.local/bin/
#   7. Generates an uninstall script
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ─── Tunables ────────────────────────────────────────────────────────────────
ATRI_VERSION="${ATRI_VERSION:-latest}"
ATRI_INSTALL_ROOT="${ATRI_INSTALL_ROOT:-$HOME/.local/share/atri}"
ATRI_BIN_DIR="${ATRI_BIN_DIR:-$HOME/.local/bin}"
ATRI_MODEL_URL="${ATRI_MODEL_URL:-https://huggingface.co/unsloth/gemma-4-E2B-it-GGUF/resolve/main/gemma-4-E2B-it-Q4_K_M.gguf}"
LLAMA_CPP_RELEASE_BASE="https://github.com/ggml-org/llama.cpp/releases/latest/download"
REPO_URL="https://github.com/ToniBirat7/Agentic_AI.git"
BRANCH="${ATRI_BRANCH:-master}"

# Directories inside ATRI_INSTALL_ROOT
LLAMA_DIR="$ATRI_INSTALL_ROOT/runtime/llama"
TEMPLATE_DIR="$ATRI_INSTALL_ROOT/runtime/templates"
MODEL_DIR="$ATRI_INSTALL_ROOT/models"
VENV_DIR="$ATRI_INSTALL_ROOT/venv"
SRC_DIR="$ATRI_INSTALL_ROOT/src"

# ─── Colors ────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'
YELLOW='\033[0;33m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

info()    { echo -e "${CYAN}  ▸${RESET} $*"; }
ok()      { echo -e "${GREEN}  ✓${RESET} $*"; }
warn()    { echo -e "${YELLOW}  ⚠${RESET} $*"; }
die()     { echo -e "${RED}  ✗ ERROR:${RESET} $*" >&2; exit 1; }
header()  { echo -e "\n${BOLD}${CYAN}── $* ──${RESET}"; }

# ─── Banner ────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${CYAN}  ╭────────────────────────────────────────╮${RESET}"
echo -e "${BOLD}${CYAN}  │  Atri Code — Local AI Coding Agent     │${RESET}"
echo -e "${BOLD}${CYAN}  │  Powered by Gemma 4 E2B + llama.cpp    │${RESET}"
echo -e "${BOLD}${CYAN}  ╰────────────────────────────────────────╯${RESET}"
echo ""

# ─── Cleanup trap (only fires on error) ────────────────────────────────────
STAGING_DIR=""
_cleanup() {
    if [ -n "$STAGING_DIR" ] && [ -d "$STAGING_DIR" ]; then
        rm -rf "$STAGING_DIR"
    fi
}
trap '_cleanup' ERR EXIT

# ─── Helper: require a command ────────────────────────────────────────────
need() { command -v "$1" &>/dev/null || die "'$1' is required but not found. Install it and retry."; }

# Check essential tools upfront
need curl
need git
need python3
need tar

# ─── Python version check (3.10+ required) ────────────────────────────────
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" \
    || die "Python 3.10+ is required (found $(python3 --version 2>&1)).\n  Install: sudo apt install python3.12  OR  brew install python@3.12"

# ─── OS / Arch Detection ──────────────────────────────────────────────────
header "Detecting system"

OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)
case "$ARCH" in
    x86_64)  ARCH_NORM="x64" ;;
    aarch64|arm64) ARCH_NORM="arm64" ;;
    *)  ARCH_NORM="$ARCH" ;;
esac

info "OS: $OS  Arch: $ARCH ($ARCH_NORM)"

# ─── GPU / Accelerator Detection ─────────────────────────────────────────
ACCEL="cpu"
COMPUTE_CAP=""

if [ "$OS" = "darwin" ] && [ "$ARCH" = "arm64" ]; then
    ACCEL="metal"
    ok "Apple Silicon → Metal"
elif command -v nvidia-smi &>/dev/null; then
    CC=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -1 | tr -d '.' || true)
    if [ -n "$CC" ]; then
        ACCEL="cuda"
        COMPUTE_CAP="$CC"
        ok "NVIDIA GPU detected (compute cap $CC) → CUDA"
    fi
fi

if [ "$ACCEL" = "cpu" ]; then
    # Check for ROCm runtime — more reliable than lspci (which also matches iGPUs)
    if command -v rocm-smi &>/dev/null && rocm-smi --showproductname &>/dev/null 2>&1; then
        ACCEL="rocm"
        ok "AMD GPU detected (rocm-smi) → ROCm"
    elif [ -d /opt/rocm ] && lspci 2>/dev/null | grep -qi 'VGA.*AMD\|3D.*AMD\|Display.*AMD'; then
        ACCEL="rocm"
        ok "AMD GPU detected (/opt/rocm + lspci) → ROCm"
    fi
fi

[ "$ACCEL" = "cpu" ] && info "No GPU detected → CPU-only mode"

# ─── Pick llama-server prebuilt asset ────────────────────────────────────
header "Selecting llama-server binary"

# LLAMA_ASSET_GREP: substring to match in release asset URL
# LLAMA_ASSET_EXCLUDE: extended-regex of substrings to exclude (grep -Ev)
# LLAMA_NEEDS_COMPILE: true = skip prebuilt, build from source
LLAMA_ASSET_GREP=""
LLAMA_ASSET_EXCLUDE="win-|\.exe$"   # always exclude Windows artifacts
LLAMA_NEEDS_COMPILE=false

case "$OS-$ARCH_NORM-$ACCEL" in
    linux-x64-cuda)
        # No CUDA prebuilt for Linux in llama.cpp releases — build from source.
        LLAMA_NEEDS_COMPILE=true
        info "NVIDIA/CUDA → building llama.cpp from source (no Linux CUDA prebuilt available)"
        ;;
    linux-x64-rocm)
        # e.g. llama-bXXXX-bin-ubuntu-rocm-7.2-x64.tar.gz
        LLAMA_ASSET_GREP="ubuntu-rocm"
        ;;
    linux-x64-cpu)
        # e.g. llama-bXXXX-bin-ubuntu-x64.tar.gz
        LLAMA_ASSET_GREP="ubuntu-x64"
        LLAMA_ASSET_EXCLUDE="$LLAMA_ASSET_EXCLUDE|vulkan|openvino|sycl|rocm|kleidiai"
        ;;
    linux-arm64-*)
        # e.g. llama-bXXXX-bin-ubuntu-arm64.tar.gz
        LLAMA_ASSET_GREP="ubuntu-arm64"
        LLAMA_ASSET_EXCLUDE="$LLAMA_ASSET_EXCLUDE|vulkan"
        ;;
    darwin-arm64-metal)
        # e.g. llama-bXXXX-bin-macos-arm64.tar.gz
        LLAMA_ASSET_GREP="macos-arm64"
        LLAMA_ASSET_EXCLUDE="$LLAMA_ASSET_EXCLUDE|kleidiai"
        ;;
    darwin-x64-*)
        LLAMA_ASSET_GREP="macos-x64"
        ;;
    *)
        LLAMA_NEEDS_COMPILE=true
        ;;
esac

# ─── Download + extract llama-server ─────────────────────────────────────
STAGING_DIR=$(mktemp -d)
mkdir -p "$LLAMA_DIR" "$TEMPLATE_DIR" "$MODEL_DIR"

if [ "$LLAMA_NEEDS_COMPILE" = "false" ] && [ -n "$LLAMA_ASSET_GREP" ]; then
    info "Fetching llama.cpp release manifest..."
    RELEASE_JSON=$(curl -fsSL "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest")
    ASSET_URL=$(echo "$RELEASE_JSON" \
        | grep "browser_download_url" \
        | grep -oE 'https://[^"]+' \
        | grep "$LLAMA_ASSET_GREP" \
        | grep -Ev "$LLAMA_ASSET_EXCLUDE" \
        | head -1 || true)

    if [ -z "$ASSET_URL" ]; then
        warn "Could not find prebuilt binary for '$OS/$ARCH/$ACCEL' — falling back to compile"
        LLAMA_NEEDS_COMPILE=true
    else
        info "Downloading: $(basename "$ASSET_URL")"
        curl -fsSL --progress-bar -o "$STAGING_DIR/llama_bin.tar.gz" "$ASSET_URL"
        mkdir -p "$STAGING_DIR/llama_extracted"
        tar xzf "$STAGING_DIR/llama_bin.tar.gz" -C "$STAGING_DIR/llama_extracted"
        # Copy only what we need: llama-server + shared libs
        LLAMA_SERVER_BIN=$(find "$STAGING_DIR/llama_extracted" -name "llama-server" ! -name "*.exe" | head -1)
        if [ -z "$LLAMA_SERVER_BIN" ]; then
            warn "llama-server not found in prebuilt archive — falling back to compile"
            LLAMA_NEEDS_COMPILE=true
        else
            cp "$LLAMA_SERVER_BIN" "$LLAMA_DIR/"
            find "$STAGING_DIR/llama_extracted" \( \
                -name "libggml*.so*" -o -name "libllama*.so*" \
                -o -name "libmtmd*.so*" -o -name "*.dylib" \) \
                -exec cp {} "$LLAMA_DIR/" \; 2>/dev/null || true
            chmod +x "$LLAMA_DIR/llama-server"
            ok "llama-server installed from prebuilt"
        fi
        rm -rf "$STAGING_DIR/llama_bin.tar.gz" "$STAGING_DIR/llama_extracted"
    fi
fi

if [ "$LLAMA_NEEDS_COMPILE" = "true" ]; then
    header "Building llama.cpp from source"
    warn "No prebuilt binary for $OS/$ARCH/$ACCEL — building from source (this takes 5-15 min)"
    need cmake
    need make

    LLAMA_SRC="$STAGING_DIR/llama_src"
    git clone --depth 1 https://github.com/ggml-org/llama.cpp.git "$LLAMA_SRC"
    cmake_flags="-DGGML_NATIVE=ON -DBUILD_SHARED_LIBS=ON"
    if [ "$ACCEL" = "cuda" ] && [ -n "$COMPUTE_CAP" ]; then
        cmake_flags="$cmake_flags -DGGML_CUDA=ON -DGGML_CUDA_ARCHITECTURES=$COMPUTE_CAP"
        # nvcc has a max supported GCC version. Auto-detect a compatible one if system GCC is too new.
        SYS_GCC_VER=$(g++ --version 2>/dev/null | grep -oP '\(GCC\) \K\d+' | head -1 || echo "0")
        if [ "${SYS_GCC_VER:-0}" -gt 14 ]; then
            CUDA_HOST_CXX=""
            for _ver in 14 13 12 11 10; do
                if command -v "g++-$_ver" &>/dev/null; then
                    CUDA_HOST_CXX=$(command -v "g++-$_ver")
                    break
                fi
            done
            if [ -n "$CUDA_HOST_CXX" ]; then
                cmake_flags="$cmake_flags -DCMAKE_CUDA_HOST_COMPILER=$CUDA_HOST_CXX"
                info "GCC $SYS_GCC_VER too new for CUDA — using host compiler: $CUDA_HOST_CXX"
            else
                warn "GCC $SYS_GCC_VER may be incompatible with CUDA. If build fails, install gcc14 (AUR: yay -S gcc14) then rerun installer."
            fi
        fi
    elif [ "$ACCEL" = "rocm" ]; then
        cmake_flags="$cmake_flags -DGGML_HIP=ON"
    fi
    cmake -S "$LLAMA_SRC" -B "$LLAMA_SRC/build" $cmake_flags -DLLAMA_BUILD_SERVER=ON \
        -DCMAKE_BUILD_TYPE=Release -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_TESTS=OFF
    cmake --build "$LLAMA_SRC/build" --target llama-server -j"$(nproc)"
    find "$LLAMA_SRC/build" -name "llama-server" | head -1 | xargs -I{} cp {} "$LLAMA_DIR/"
    find "$LLAMA_SRC/build" \( -name "libggml*.so*" -o -name "libllama*.so*" -o -name "libmtmd*.so*" \) \
        -exec cp {} "$LLAMA_DIR/" \; 2>/dev/null || true
    chmod +x "$LLAMA_DIR/llama-server"
    ok "llama-server built from source"
fi

# Verify llama-server exists
[ -f "$LLAMA_DIR/llama-server" ] || die "llama-server binary not found after install"

# ─── Install chat template ─────────────────────────────────────────────────
header "Installing Gemma 4 chat template"

# The template ships in the source repo; we clone a shallow copy to get it
if [ ! -f "$TEMPLATE_DIR/gemma4-tooluse.jinja" ]; then
    ATRI_TEMPLATE_SRC="$STAGING_DIR/atri_src"
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$ATRI_TEMPLATE_SRC" 2>/dev/null || true
    if [ -f "$ATRI_TEMPLATE_SRC/runtime/templates/gemma4-tooluse.jinja" ]; then
        cp "$ATRI_TEMPLATE_SRC/runtime/templates/gemma4-tooluse.jinja" "$TEMPLATE_DIR/"
        ok "Gemma 4 Jinja template installed"
    fi
fi

# ─── Install orchestrator + CLI ────────────────────────────────────────────
header "Installing Atri Code (orchestrator + CLI)"

# Clone/update source
if [ -d "$SRC_DIR/.git" ]; then
    info "Updating existing source..."
    git -C "$SRC_DIR" fetch origin
    git -C "$SRC_DIR" checkout "$BRANCH"
    git -C "$SRC_DIR" pull --ff-only origin "$BRANCH" 2>/dev/null || true
else
    info "Cloning Atri Code source..."
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$SRC_DIR"
fi

# Create venv + install packages
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install -q --upgrade pip
"$VENV_DIR/bin/pip" install -q -r "$SRC_DIR/services/orchestrator/requirements.txt"
"$VENV_DIR/bin/pip" install -q -r "$SRC_DIR/apps/cli/requirements.txt" 2>/dev/null || true
"$VENV_DIR/bin/pip" install -q -e "$SRC_DIR/apps/cli"

# Set up .env if missing
if [ ! -f "$SRC_DIR/services/orchestrator/.env" ]; then
    cp "$SRC_DIR/services/orchestrator/.env.example" "$SRC_DIR/services/orchestrator/.env"
    ok ".env created from template"
fi

# Patch database URL to absolute path so it works regardless of orchestrator CWD
DB_STATE_DIR="$SRC_DIR/runtime/state"
mkdir -p "$DB_STATE_DIR"
sed -i "s|ORCHESTRATOR_DATABASE_URL=.*|ORCHESTRATOR_DATABASE_URL=sqlite:///${DB_STATE_DIR}/orchestrator.db|" \
    "$SRC_DIR/services/orchestrator/.env"

# Write hardware config (saved to $SRC_DIR/runtime/llm/launch_config.json)
"$VENV_DIR/bin/python" "$SRC_DIR/scripts/detect_hardware.py" --save \
    --install-root "$SRC_DIR" 2>/dev/null || true

ok "Orchestrator + CLI installed"

# ─── Create `atri` launcher ────────────────────────────────────────────────
header "Creating launcher"

mkdir -p "$ATRI_BIN_DIR"
cat > "$ATRI_BIN_DIR/atri" <<LAUNCHER
#!/usr/bin/env bash
# Atri Code launcher — generated by install.sh
export ATRI_INSTALL_ROOT="$ATRI_INSTALL_ROOT"
export LLAMA_SERVER_BIN="$LLAMA_DIR/llama-server"
export ATRI_TEMPLATE_DIR="$TEMPLATE_DIR"
export ATRI_MODEL_DIR="$MODEL_DIR"
export ATRI_SRC_DIR="$SRC_DIR"
export LD_LIBRARY_PATH="$LLAMA_DIR\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
exec "$VENV_DIR/bin/atri" "\$@"
LAUNCHER
chmod +x "$ATRI_BIN_DIR/atri"
ok "atri launcher → $ATRI_BIN_DIR/atri"

# ─── PATH check ────────────────────────────────────────────────────────────
SENTINEL="# >>> atri-code installer added >>>"
if [[ ":$PATH:" != *":$ATRI_BIN_DIR:"* ]]; then
    for RC in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
        if [ -f "$RC" ] && ! grep -qF "$SENTINEL" "$RC" 2>/dev/null; then
            {
                echo ""
                echo "$SENTINEL"
                echo "export PATH=\"$ATRI_BIN_DIR:\$PATH\""
                echo "# <<< atri-code installer added <<<"
            } >> "$RC"
            info "Added $ATRI_BIN_DIR to PATH in $(basename "$RC")"
        fi
    done
    export PATH="$ATRI_BIN_DIR:$PATH"
fi

# ─── Lazy model fetch on first run ────────────────────────────────────────
# Model is NOT downloaded here to keep installer fast.
# atri service_manager downloads it on first `atri` invocation.
FIRST_RUN_MARKER="$MODEL_DIR/.fetch_on_first_run"
if [ ! -f "$MODEL_DIR/gemma-4-E2B-it-Q4_K_M.gguf" ]; then
    echo "MODEL_URL=$ATRI_MODEL_URL" > "$FIRST_RUN_MARKER"
    info "Model will be downloaded (~3.1 GB) on first 'atri' run"
fi

# ─── Uninstall script ──────────────────────────────────────────────────────
cat > "$ATRI_INSTALL_ROOT/uninstall.sh" <<UNINSTALL
#!/usr/bin/env bash
# Atri Code uninstaller — removes everything under $ATRI_INSTALL_ROOT
set -e
echo "Removing Atri Code..."
rm -rf "$ATRI_INSTALL_ROOT"
rm -f  "$ATRI_BIN_DIR/atri"
# Remove PATH block from shell rc files
for RC in "\$HOME/.bashrc" "\$HOME/.zshrc" "\$HOME/.profile"; do
    if [ -f "\$RC" ]; then
        sed -i '/# >>> atri-code installer added >>>/,/# <<< atri-code installer added <<</d' "\$RC" 2>/dev/null || true
    fi
done
echo "Atri Code removed. Restart your shell to apply PATH changes."
UNINSTALL
chmod +x "$ATRI_INSTALL_ROOT/uninstall.sh"
ok "Uninstall script → $ATRI_INSTALL_ROOT/uninstall.sh"

# ─── Clean up staging ──────────────────────────────────────────────────────
rm -rf "$STAGING_DIR"
STAGING_DIR=""  # prevent trap from double-cleaning

# ─── Summary ───────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}  ╭────────────────────────────────────────╮${RESET}"
echo -e "${BOLD}${GREEN}  │  Installation Complete!                 │${RESET}"
echo -e "${BOLD}${GREEN}  │                                         │${RESET}"
echo -e "${BOLD}${GREEN}  │  Accelerator: ${ACCEL}$(printf '%*s' $((23 - ${#ACCEL})) '')│${RESET}"
echo -e "${BOLD}${GREEN}  │                                         │${RESET}"
echo -e "${BOLD}${GREEN}  │  Start:    atri                         │${RESET}"
echo -e "${BOLD}${GREEN}  │  Diagnose: atri doctor                  │${RESET}"
echo -e "${BOLD}${GREEN}  │  Remove:   $ATRI_INSTALL_ROOT/uninstall.sh${RESET}"
echo -e "${BOLD}${GREEN}  ╰────────────────────────────────────────╯${RESET}"
echo ""
echo -e "${DIM}  Restart your shell or run: export PATH=\"$ATRI_BIN_DIR:\$PATH\"${RESET}"
echo ""
