#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Atri Code — One-command installer
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/ToniBirat7/Agentic_AI/master/install.sh | bash
#
# This script:
#   1. Checks/installs prerequisites (python3, git, cmake)
#   2. Clones or updates the Atri Code repository
#   3. Runs the full bootstrap (deps, model download, llama.cpp build, services)
#   4. Installs the `atri-cli` launcher into ~/.local/bin
#   5. Verifies everything works with `atri-cli doctor`
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_URL="https://github.com/ToniBirat7/Agentic_AI.git"
INSTALL_DIR="${ATRI_INSTALL_DIR:-$HOME/.local/share/atri-code}"
BRANCH="${ATRI_BRANCH:-master}"
BIN_DIR="$HOME/.local/bin"

# ─── Colors ────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

info()    { echo -e "${CYAN}  [INFO]${RESET} $*"; }
success() { echo -e "${GREEN}  [OK]${RESET} $*"; }
warn()    { echo -e "${RED}  [ERROR]${RESET} $*"; }
header()  { echo -e "\n${BOLD}${CYAN}  --- $* ---${RESET}\n"; }

# ─── Banner ────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${CYAN}  ╭──────────────────────────────────────╮${RESET}"
echo -e "${BOLD}${CYAN}  │  Atri Code Installer                 │${RESET}"
echo -e "${BOLD}${CYAN}  │  Local AI coding agent                │${RESET}"
echo -e "${BOLD}${CYAN}  ╰──────────────────────────────────────╯${RESET}"
echo ""

# ─── OS Detection ─────────────────────────────────────────────────────────
detect_os() {
    case "$(uname -s)" in
        Linux*)   echo "linux" ;;
        Darwin*)  echo "macos" ;;
        MINGW*|MSYS*|CYGWIN*) echo "windows" ;;
        *)        echo "unknown" ;;
    esac
}

OS=$(detect_os)
info "Detected OS: $OS"

# ─── Prerequisite checks ──────────────────────────────────────────────────
check_command() {
    if command -v "$1" &>/dev/null; then
        success "$1 found: $(command -v "$1")"
        return 0
    else
        warn "$1 not found"
        return 1
    fi
}

install_missing_deps() {
    local missing=()
    
    command -v python3 &>/dev/null || missing+=("python3")
    command -v git     &>/dev/null || missing+=("git")
    command -v cmake   &>/dev/null || missing+=("cmake")
    command -v make    &>/dev/null || missing+=("make")
    
    if [ ${#missing[@]} -eq 0 ]; then
        return 0
    fi
    
    info "Missing: ${missing[*]}"
    echo ""
    
    if [ "$OS" = "linux" ]; then
        if command -v pacman &>/dev/null; then
            info "Installing via pacman..."
            sudo pacman -S --needed --noconfirm "${missing[@]}" 2>/dev/null || true
        elif command -v apt-get &>/dev/null; then
            info "Installing via apt..."
            # Map python3 to python3 + python3-venv
            local apt_pkgs=()
            for pkg in "${missing[@]}"; do
                apt_pkgs+=("$pkg")
                if [ "$pkg" = "python3" ]; then
                    apt_pkgs+=("python3-venv" "python3-pip")
                fi
            done
            sudo apt-get update -qq && sudo apt-get install -y -qq "${apt_pkgs[@]}" 2>/dev/null || true
        elif command -v dnf &>/dev/null; then
            info "Installing via dnf..."
            sudo dnf install -y "${missing[@]}" 2>/dev/null || true
        fi
    elif [ "$OS" = "macos" ]; then
        if command -v brew &>/dev/null; then
            info "Installing via Homebrew..."
            brew install "${missing[@]}" 2>/dev/null || true
        else
            warn "Homebrew not found. Install missing tools manually: ${missing[*]}"
            exit 1
        fi
    fi
}

header "Checking prerequisites"

check_command python3 || true
check_command git     || true
check_command cmake   || true

# Try to install missing deps
install_missing_deps

# Final verification
for cmd in python3 git cmake; do
    if ! command -v "$cmd" &>/dev/null; then
        warn "Required command '$cmd' is still missing. Please install it manually."
        exit 1
    fi
done

# Check Python version (need >= 3.10)
PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    warn "Python 3.10+ required, found $PY_VERSION"
    exit 1
fi
success "Python $PY_VERSION"

# ─── Clone / Update Repository ────────────────────────────────────────────
header "Setting up Atri Code"

if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing installation at $INSTALL_DIR"
    cd "$INSTALL_DIR"
    git fetch origin
    git checkout "$BRANCH"
    git pull --ff-only origin "$BRANCH" 2>/dev/null || true
    git submodule update --init --recursive
else
    info "Cloning Atri Code to $INSTALL_DIR"
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone --recurse-submodules --single-branch --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"
success "Repository ready at $INSTALL_DIR"

# ─── Run Bootstrap ─────────────────────────────────────────────────────────
header "Running bootstrap (this may take a few minutes)"
info "Building llama.cpp, downloading model, installing dependencies..."
echo ""

python3 scripts/local_up.py \
    --repo-dir "$INSTALL_DIR" \
    --branch "$BRANCH" \
    --skip-clone \
    --mode cli

# ─── Ensure PATH ───────────────────────────────────────────────────────────
header "Finalizing installation"

mkdir -p "$BIN_DIR"
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    # Add to shell rc
    for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
        if [ -f "$rc" ]; then
            if ! grep -q 'atri-code' "$rc" 2>/dev/null; then
                echo '' >> "$rc"
                echo '# Atri Code' >> "$rc"
                echo "export PATH=\"\$HOME/.local/bin:\$PATH\"" >> "$rc"
                info "Added ~/.local/bin to PATH in $(basename "$rc")"
            fi
        fi
    done
    export PATH="$BIN_DIR:$PATH"
fi

# ─── Verification ──────────────────────────────────────────────────────────
header "Verifying installation"

if command -v atri &>/dev/null; then
    success "atri is available at $(command -v atri)"
else
    warn "atri not found in PATH"
    info "Try: export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

# Run doctor check
echo ""
atri doctor 2>/dev/null && success "All systems operational" || warn "Some checks failed — run 'atri doctor' for details"

# ─── Summary ───────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${CYAN}  ╭──────────────────────────────────────╮${RESET}"
echo -e "${BOLD}${CYAN}  │  - Installation Complete!             │${RESET}"
echo -e "${BOLD}${CYAN}  │                                       │${RESET}"
echo -e "${BOLD}${CYAN}  │  Start Atri Code:                     │${RESET}"
echo -e "${BOLD}${CYAN}  │    $ atri                             │${RESET}"
echo -e "${BOLD}${CYAN}  │                                       │${RESET}"
echo -e "${BOLD}${CYAN}  │  One-shot mode:                       │${RESET}"
echo -e "${BOLD}${CYAN}  │    $ atri \"your prompt here\"          │${RESET}"
echo -e "${BOLD}${CYAN}  │                                       │${RESET}"
echo -e "${BOLD}${CYAN}  │  Diagnostics:                         │${RESET}"
echo -e "${BOLD}${CYAN}  │    $ atri doctor                      │${RESET}"
echo -e "${BOLD}${CYAN}  ╰──────────────────────────────────────╯${RESET}"
echo ""