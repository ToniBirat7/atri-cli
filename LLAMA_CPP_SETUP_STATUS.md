# llama.cpp Setup Status & Implementation Guide

**Date:** April 18, 2026  
**Question:** Are we running llama.cpp for the entire CLI and Web pipeline?  
**Answer:** NO — It's configured but not running. Here's how to fix it.

---

## Current Status

### ✅ What's Already Done (Configuration)
- Orchestrator is **designed** to use llama.cpp
- Config file specifies: `LLM_BASE_URL = http://127.0.0.1:8000/v1`
- LLMAdapter is implemented to communicate with llama.cpp
- CLI is wired to route LLM requests through orchestrator
- All infrastructure assumes llama.cpp on port 8000

### ❌ What's Missing (Runtime)
- **llama.cpp is NOT running** (port 8000 is empty)
- **Ollama is running** but has no models installed
- **Previous testing used a stub LLM** (temporary workaround, not production)
- **Full pipeline cannot work** without LLM backend

### Service Status Check Results
```
llama.cpp (port 8000):     ❌ NOT RUNNING
Orchestrator (port 8001):  🟡 Running but LLM requests will fail
Ollama (port 11434):       ✅ Running, but no models
CLI:                       🟡 Ready, but backend unavailable
```

---

## The Problem Explained

Your architecture expects this flow:

```
USER QUERY
    ↓
CLI (tarbar_cli.main)
    ↓
Orchestrator (port 8001)
    ↓
LLM Adapter
    ↓
llama.cpp (port 8000) ← ❌ THIS IS MISSING
    ↓
AI Reasoning & Tool Selection
    ↓
Tool Execution (MCP)
    ↓
Response to User
```

**Current broken behavior:**
```
CLI → Orchestrator → [tries to connect to port 8000] → ❌ CONNECTION REFUSED
```

---

## Solution 1: Using Ollama (Recommended for Development)

Ollama provides an OpenAI-compatible API that works as a drop-in replacement for llama.cpp.

### Step 1: Pull a Model (5-30 minutes, one-time)

```bash
# Terminal 1
ollama pull mistral    # Fast model, good reasoning (~4GB)
# OR
ollama pull neural-chat  # Smaller, faster (~3GB)
```

Verify:
```bash
curl http://localhost:11434/api/tags | jq '.models[].name'
```

Expected output:
```
"mistral:latest"
```

### Step 2: Update Orchestrator Configuration

**Option A: Environment Variable (Recommended)**
```bash
# Set before starting orchestrator
export LLM_BASE_URL=http://127.0.0.1:11434/v1
```

**Option B: Edit config.py (Permanent)**
Edit [services/orchestrator/config.py](services/orchestrator/config.py#L20-L24):

```python
base_url: str = Field(
    default="http://127.0.0.1:11434/v1",  # Changed from 8000 to 11434
    description="llama.cpp OpenAI-compatible API endpoint"
)
```

### Step 3: Start the Full Pipeline

```bash
# Terminal 1: Ollama is already running (if started)
# If not: ollama serve

# Terminal 2: Start Orchestrator
cd /run/media/tonibirat/New\ Volume/AI_ML_Complete/Agentic_AI/services/orchestrator
export LLM_BASE_URL=http://127.0.0.1:11434/v1
python -m api

# Terminal 3: Verify orchestrator is ready
curl http://127.0.0.1:8001/health

# Terminal 4: Test CLI with real LLM
cd /run/media/tonibirat/New\ Volume/AI_ML_Complete/Agentic_AI
python -m tarbar_cli.main \
  --api-url http://127.0.0.1:8001 \
  --allowed-directory . \
  mcp chat \
  --prompt "List all Python files in the workspace"
```

---

## Solution 2: Running Real llama.cpp (Production)

### Step 1: Get a Model in GGUF Format

```bash
# Download pre-converted model
# From: https://huggingface.co/models?search=gguf

# Example: Mistral GGUF
wget https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/resolve/main/mistral-7b-instruct-v0.2.Q4_K_M.gguf -O ~/models/mistral.gguf
```

### Step 2: Compile llama.cpp

```bash
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
make -j4

# With GPU support (CUDA)
make LLAMA_CUDA=1 -j4
```

### Step 3: Start Server on Port 8000

```bash
# CPU only
./llama.cpp/server -m ~/models/mistral.gguf \
  -ngl 0 \
  --port 8000 \
  --host 127.0.0.1

# GPU support (NVIDIA)
./llama.cpp/server -m ~/models/mistral.gguf \
  -ngl 99 \
  --port 8000 \
  --host 127.0.0.1

# With threads optimization
./llama.cpp/server -m ~/models/mistral.gguf \
  -ngl 99 \
  -t 8 \
  --port 8000 \
  --host 127.0.0.1
```

### Step 4: Verify and Start Pipeline

```bash
# Test llama.cpp is responding
curl http://127.0.0.1:8000/health

# Start orchestrator (config already points to 8000)
cd services/orchestrator
python -m api

# Use CLI (no environment variable needed, default is already 8000)
python -m tarbar_cli.main --api-url http://127.0.0.1:8001 mcp chat --prompt "test"
```

---

## Solution 3: Docker (Production-Ready)

```bash
# Terminal 1: Run llama.cpp in Docker on port 8000
docker run -p 8000:8000 \
  ghcr.io/ggerganov/llama.cpp:server-latest \
  -m mistral \
  -ngl 99

# Terminal 2: Start orchestrator (as above)
cd services/orchestrator
python -m api

# Terminal 3: Use CLI (as above)
python -m tarbar_cli.main ...
```

---

## Testing the Full Pipeline

### Quick Test (One-shot)
```bash
python -m tarbar_cli.main \
  --api-url http://127.0.0.1:8001 \
  --allowed-directory /run/media/tonibirat/New\ Volume/AI_ML_Complete/Agentic_AI \
  mcp chat \
  --prompt "What Python files are in the workspace?"
```

### Full Test (Multi-turn Interactive)
```bash
python -m tarbar_cli.main \
  --api-url http://127.0.0.1:8001 \
  --allowed-directory /run/media/tonibirat/New\ Volume/AI_ML_Complete/Agentic_AI
```

Then type:
```
/help
List the MCP service files
Search for all .py files
Read services/mcp/main.py and tell me what it does
/exit
```

### Expected Behavior (with Real LLM)
✅ CLI sends prompt to orchestrator  
✅ Orchestrator sends to llama.cpp (Ollama or local)  
✅ LLM reasons about request  
✅ LLM decides which tool to call (intelligently, not hardcoded)  
✅ Tool executes (list, search, read files)  
✅ LLM receives tool result  
✅ LLM generates final response  
✅ CLI displays result  

### Performance Expectations
- **Ollama (Mistral):** 500-1500ms per request
- **Local llama.cpp:** 300-1000ms per request (depends on GPU)
- **Docker llama.cpp:** 400-1200ms per request

---

## Troubleshooting

| Problem                                       | Solution                                                                     |
| --------------------------------------------- | ---------------------------------------------------------------------------- |
| `Connection refused` on port 8000             | Start llama.cpp/Ollama on that port                                          |
| `curl localhost:8000/health` returns 404      | llama.cpp server not running                                                 |
| Ollama says "no models installed"             | Run `ollama pull mistral` first                                              |
| Orchestrator starts but timeouts on LLM calls | LLM server too slow or not responding; check `curl localhost:8000/v1/models` |
| CLI hangs when sending prompt                 | LLM is processing (first request is slow); wait 10-30 seconds                |
| "Model not found" error in logs               | Check model name matches: `curl localhost:11434/api/tags`                    |
| High latency (>5s per request)                | Model might be loading to GPU; first request is always slow                  |

---

## Summary: What to Do Now

**To get llama.cpp running for your full pipeline:**

### Fastest (Development):
```bash
# 1. Install model in Ollama
ollama pull mistral

# 2. Update orchestrator to use Ollama
export LLM_BASE_URL=http://127.0.0.1:11434/v1

# 3. Start orchestrator
cd services/orchestrator && python -m api

# 4. Test CLI
python -m tarbar_cli.main --api-url http://127.0.0.1:8001 mcp chat --prompt "test"
```

### Production Ready (Local GPU):
```bash
# 1. Compile llama.cpp with GPU support
cd llama.cpp && make LLAMA_CUDA=1

# 2. Download model
wget <gguf-model-url> -O model.gguf

# 3. Start server (uses port 8000, which config already expects)
./server -m model.gguf -ngl 99 --port 8000

# 4. Start orchestrator & CLI (no config changes needed)
```

### Cloud/Docker:
```bash
# Just run container on port 8000, start orchestrator & CLI
docker run -p 8000:8000 ghcr.io/ggerganov/llama.cpp:server-latest
```

**The key point:** Your orchestrator is already wired for llama.cpp on port 8000. You just need to start the backend service.
