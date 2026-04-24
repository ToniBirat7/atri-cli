# Atri Code Quick Start Guide

This guide provides the technical steps required to initialize and verify the Atri Code environment.

## Installation

Run the official one-line installer to configure the environment, build the local inference engine, and deploy background services:

```bash
curl -fsSL https://raw.githubusercontent.com/ToniBirat7/Agentic_AI/master/install.sh | bash
```

## Post-Installation Verification

### 1. System Health Check
Use the `doctor` command to verify that the local LLM server, orchestrator, and MCP tool registry are operational:

```bash
atri-cli doctor
```

### 2. Basic Interaction
Initialize a session to verify connectivity with the local inference engine:

```bash
atri-cli "What is the current version of Atri Code?"
```

## Service Management

Atri Code operates using persistent background daemons to ensure low-latency performance.

| Action | Command |
| :--- | :--- |
| **Start/Update Services** | `atri-cli doctor` |
| **Stop Services** | `atri-cli stop` |
| **View Service Status** | `atri-cli status` |

## Core Commands

- **Interactive Mode**: Launch the full TUI with `atri-cli`.
- **Permission Management**: Toggle security levels with `/mode` within the TUI.
- **Session Clear**: Reset conversation context with `/clear`.
- **System Upgrade**: Pull the latest performance optimizations with `atri-cli upgrade`.

---

## Directory Structure (Production)

- `apps/cli/atri_cli`: Primary terminal interface and service manager.
- `services/orchestrator`: Core agent loop and reasoning logic.
- `services/mcp`: Tool registry and environment adapters.
- `runtime/`: Persistent state, logs, and compiled bytecode.
- `models/`: Optimized GGUF model binaries.
