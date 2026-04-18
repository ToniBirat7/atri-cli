# Real LLM Backend Testing Guide

**Created:** April 18, 2026  
**Purpose:** Complete walkthrough for running the CLI test suite against a real LLM backend instead of the stub

---

## Table of Contents

1. [What It Means: Stub vs Real LLM](#what-it-means-stub-vs-real-llm)
2. [Current State](#current-state)
3. [Step-by-Step: How to Test with Real Ollama](#step-by-step-how-to-test-with-real-ollama)
4. [Step-by-Step: How to Test with OpenAI](#step-by-step-how-to-test-with-openai)
5. [Expected Results & Comparison](#expected-results--comparison)
6. [Why This Matters](#why-this-matters)

---

## What It Means: Stub vs Real LLM

### **Stub LLM (What We've Been Using)**

The stub is a **fake LLM server** for testing:

```
┌─────────────────────────────────────────┐
│  Your CLI Query                         │
│  "List the workspace files"             │
└──────────────────┬──────────────────────┘
                   │
                   ▼
         ┌─────────────────────┐
         │  Orchestrator       │
         │  (port 8001)        │
         └──────────┬──────────┘
                    │
                    ▼
          ┌────────────────────────┐
          │  STUB LLM (port 8000)  │  ◄── Fake/deterministic
          │  - No real reasoning   │     responses
          │  - Hardcoded responses │
          │  - ~50ms latency       │
          └────────────────────────┘
```

**Characteristics:**
- **Deterministic**: Always returns same response for same prompt
- **Fast**: ~50-100ms per response (no reasoning)
- **Predictable**: First turn = suggest tool, second turn = final answer
- **Perfect for infrastructure testing**: Confirms system works

**Limitations:**
- No real AI reasoning
- Can't evaluate actual model quality
- Doesn't measure real-world performance
- Tool selection is hardcoded

### **Real LLM (What We Want to Test Against)**

A **genuine language model** that reasons about your prompts:

```
┌─────────────────────────────────────────┐
│  Your CLI Query                         │
│  "List the workspace files"             │
└──────────────────┬──────────────────────┘
                   │
                   ▼
         ┌─────────────────────┐
         │  Orchestrator       │
         │  (port 8001)        │
         └──────────┬──────────┘
                    │
                    ▼
    ┌──────────────────────────────────┐
    │  REAL LLM (Ollama or OpenAI)     │  ◄── Actual AI
    │  - Real reasoning                │     model
    │  - Intelligent tool selection    │
    │  - 500-2000ms latency            │
    │  - Unpredictable responses       │
    └──────────────────────────────────┘
```

**Characteristics:**
- **Intelligent**: Reasons about your request
- **Slower**: 500-2000ms+ per response (depends on model size)
- **Variable**: Different responses based on prompt variations
- **Real-world**: Represents actual production behavior

**Benefits:**
- Measure actual performance impact
- Verify model quality and reasoning
- Test error cases (bad reasoning, hallucinations)
- Compare different models

---

## Current State

### **Environment Check**

```bash
# What we detected:
✓ Ollama: Running on localhost:11434
✗ Ollama Models: NONE installed
✓ Stub LLM: Can run anytime
✗ OpenAI API: No API key configured
```

### **What This Means**

- **Ollama is installed and running** but has no models downloaded
- **To test with real Ollama**, you need to download a model (takes 5-30 min)
- **To test with OpenAI**, you need an API key (free trial available)
- **Stub LLM is always ready** for infrastructure testing

---

## Step-by-Step: How to Test with Real Ollama

### **Step 1: Pull a Model (One-Time Setup)**

```bash
# Terminal 1: Pull a fast model (takes 5-15 minutes)
ollama pull mistral

# Verify it's installed
curl -s http://localhost:11434/api/tags | jq .
```

**Expected output:**
```json
{
  "models": [
    {
      "name": "mistral:latest",
      "digest": "...",
      "size": 4109037760,
      "modified_time": "2024-01-01T12:00:00Z"
    }
  ]
}
```

### **Step 2: Update Orchestrator Configuration**

The orchestrator expects a `llama.cpp` OpenAI-compatible API. Ollama provides this, but we need to set the right URL.

**Option A: Environment Variable (Quick)**
```bash
export LLM_BASE_URL=http://127.0.0.1:11434/v1
```

**Option B: Modify config.py**
Edit [services/orchestrator/config.py](services/orchestrator/config.py#L20-L24):
```python
class LLMConfig(BaseModel):
    base_url: str = Field(
        default="http://127.0.0.1:11434/v1",  # ◄── Changed from http://127.0.0.1:8000/v1
        description="LLM API endpoint"
    )
```

### **Step 3: Start the Test Suite**

```bash
# Terminal 2: From workspace root
cd /run/media/tonibirat/New\ Volume/AI_ML_Complete/Agentic_AI

# Run the comparison test (see below for script)
python test_real_llm.py
```

### **Step 4: Observe Results**

**Expected behavior:**
- First request: ~1000-3000ms (model downloads from cache, reasoning happens)
- Subsequent requests: ~500-1000ms (cached, faster)
- Model will call tools intelligently (not hardcoded)
- Responses are unpredictable based on model reasoning

---

## Step-by-Step: How to Test with OpenAI

### **Step 1: Get API Key**

1. Sign up: https://platform.openai.com/signup
2. Create API key: https://platform.openai.com/api/keys
3. Copy the key

### **Step 2: Configure Environment**

```bash
# Terminal 1: Set API key
export OPENAI_API_KEY="sk-proj-..."

# Optional: Verify it works
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  | jq '.data | length'
```

### **Step 3: Update Orchestrator Configuration**

**Option A: Create `.env` file in orchestrator directory**
```bash
cat > services/orchestrator/.env << 'EOF'
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4-mini
OPENAI_API_KEY=sk-proj-...
EOF
```

**Option B: Set environment variables**
```bash
export LLM_BASE_URL=https://api.openai.com/v1
export LLM_MODEL=gpt-4-mini
export OPENAI_API_KEY=sk-proj-...
```

### **Step 4: Start the Test Suite**

```bash
cd /run/media/tonibirat/New\ Volume/AI_ML_Complete/Agentic_AI
python test_real_llm_openai.py
```

---

## Expected Results & Comparison

### **Latency Comparison**

| Scenario             | Stub LLM | Ollama (Mistral) | OpenAI (GPT-4-mini) |
| -------------------- | -------- | ---------------- | ------------------- |
| Smoke (mcp status)   | ~85ms    | ~90ms            | ~400ms              |
| One-shot list        | ~260ms   | ~800ms           | ~500ms              |
| One-shot search      | ~325ms   | ~900ms           | ~600ms              |
| One-shot read        | ~360ms   | ~750ms           | ~550ms              |
| Multi-turn (3 turns) | ~730ms   | ~2500ms          | ~1500ms             |

**Key Insights:**
- Stub: Network overhead only (~50-100ms base + request routing)
- Ollama: Network overhead + model inference (~700-900ms per turn)
- OpenAI: Network overhead + API latency + model (higher consistency but slower)

### **Quality Comparison**

| Aspect            | Stub                  | Ollama       | OpenAI           |
| ----------------- | --------------------- | ------------ | ---------------- |
| Tool Selection    | Hardcoded             | Intelligent  | Very Intelligent |
| Path Targeting    | Always workspace root | Variable     | Usually correct  |
| Error Handling    | Deterministic         | Realistic    | Production-grade |
| Cost              | Free                  | Free (local) | $$$ (per token)  |
| Reasoning Quality | N/A                   | Good         | Excellent        |

---

## Why This Matters

### **Stub LLM Use Cases**
- ✅ System integration testing
- ✅ Performance baseline (backend latency)
- ✅ Permission evaluation correctness
- ✅ Tool execution flow
- ❌ Not realistic for production

### **Real LLM Use Cases**
- ✅ Production-realistic performance
- ✅ Model quality evaluation
- ✅ Edge case discovery
- ✅ Actual bottleneck identification
- ✅ Cost estimation
- ✅ Real-world behavior validation

### **Typical Testing Pyramid**

```
        ┌─────────────────┐
        │  Real LLM Tests │  ◄── Slow, realistic
        │  (Few, expensive)   
        └─────────────────┘
             ▲
      ┌──────────────────┐
      │  Integration     │  ◄── Medium speed
      │  Tests (Stub)    │     Deterministic
      └──────────────────┘
             ▲
      ┌──────────────────┐
      │  Unit Tests      │  ◄── Fast, isolated
      │  (No LLM)        │     Many tests
      └──────────────────┘
```

**Best Practice:**
1. Use **Stub LLM** for CI/CD (fast feedback)
2. Use **Real LLM** for nightly/weekly runs (production-like)
3. Use **OpenAI** for important customer paths (highest quality)

---

## Test Script Templates

### **Template 1: Stub vs Real Comparison**

```python
# See: test_llm_comparison.py (attached)
# Runs 5 test scenarios against both backends
# Compares latency, success rate, output quality
```

### **Template 2: Single Real LLM Test**

```python
import subprocess
import os

os.environ['LLM_BASE_URL'] = 'http://127.0.0.1:11434/v1'

cmd = [
    'python', '-m', 'tarbar_cli.main',
    '--api-url', 'http://127.0.0.1:8001',
    '--allowed-directory', '/path/to/workspace',
    'mcp', 'chat',
    '--prompt', 'List all Python files'
]

result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
print(f"Exit: {result.returncode}")
print(f"Output:\n{result.stdout}")
if result.stderr:
    print(f"Errors:\n{result.stderr}")
```

### **Template 3: Latency Breakdown**

```python
# Measure individual components:
# - CLI startup: ~50ms
# - Orchestrator route: ~10ms
# - LLM inference: ~500-3000ms ◄── Main bottleneck
# - Permission evaluation: ~5-10ms
# - Tool execution: ~50-200ms
```

---

## Troubleshooting

| Problem              | Solution                                                                        |
| -------------------- | ------------------------------------------------------------------------------- |
| "Connection refused" | Check Ollama/OpenAI is running: `curl localhost:11434/health`                   |
| "Model not found"    | Download model: `ollama pull mistral`                                           |
| "Rate limited"       | OpenAI quota exceeded. Wait or use local Ollama                                 |
| "Timeout after 30s"  | Model too large or slow. Increase timeout or use smaller model                  |
| "Tool not called"    | Check LLM reasoning. Real models sometimes don't use tools. Try clearer prompts |

---

## Summary

**What "real LLM backend testing" means:**
- Replace the deterministic stub with an actual AI model
- Measure production-realistic performance
- Verify model quality and reasoning
- Identify real bottlenecks (usually LLM inference, not infrastructure)

**To get started:**
1. **For local testing**: `ollama pull mistral` (fast, free)
2. **For production testing**: Use OpenAI (highest quality)
3. **For CI/CD**: Keep using Stub LLM (fast, deterministic)

**Expected outcome:**
- 3-10x slower than stub (model inference dominates)
- More realistic tool selection
- Better understanding of production behavior
- Data-driven optimization decisions
