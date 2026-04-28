# Atri Code CLI

The interactive command-line interface for the Atri Code agentic infrastructure.

## Features
- **Interactive TUI**: Rich terminal interface with real-time turn monitoring.
- **Permission Control**: Strict runtime evaluation of tool-call permissions.
- **Telemetry**: Built-in performance and success-rate tracking.
- **Service Management**: Automatic lifecycle control for background LLM and Orchestrator services.

## Installation
From the project root:
```bash
make install
```

## Usage
Start the interactive session:
```bash
atri
```

One-shot prompt:
```bash
atri "refactor main.py to use a class"
```

Diagnostics:
```bash
atri doctor
```
