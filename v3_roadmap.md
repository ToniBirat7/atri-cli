# Atri-Code v3: The Claude-Parity Roadmap

**Project Objective**: Transform Atri-Code from a simple agent into a state-aware, high-reliability engineering harness that provides a "Claude Code" experience on local consumer hardware (RTX 3060 / 6GB VRAM).

---

## 🟢 Phase 1: The "Battle of the Brains" (Evaluation)
**Goal**: Finalize the core reasoning engine for v3.

- [ ] **Benchmark Suite**: Run a standardized "Tool-Accuracy" test on all 4 models:
    - Gemma 4 e2b (Baseline)
    - Gemma 4 E4B (Reasoning variant)
    - Llama 3.2 3B (Speed variant)
    - Qwen 2.5 Coder 3B (Coding variant)
- [ ] **Template Optimization**: Create unique prompt templates for each model (Qwen IM, Llama Header, Gemma Turn) to ensure 100% compliance.
- [ ] **Selection**: Finalize the default model based on "Success Rate @ Tool Call" and "Hallucination Rate."

---

## 🔵 Phase 2: The "Semantic Core" (Memory & Context)
**Goal**: Solve the 64k context limit using intelligent indexing.

- [ ] **Local Indexer (RAG-lite)**:
    - Implement a background indexing service using `nomic-embed-text`.
    - Store embeddings in a local SQLite database (`.atri/index.db`).
    - Expose `semantic_search` tool to the agent.
- [ ] **Prefix Caching**:
    - Update `mcp_orchestrator.py` to enable `llama.cpp` slot-saving.
    - Result: Instant responses for Turn 2+ in a session.
- [ ] **Context Manager**:
    - Implement "Recursive Summarization" to keep the context window lean during long sessions.

---

## 🟡 Phase 3: The "Architect" Engine (Tools & Diffs)
**Goal**: Move from "File Rewriting" to "Patch-Based Editing."

- [ ] **Search-Replace Tool**:
    - Implement a tool that accepts `SEARCH` and `REPLACE` blocks.
    - Build a robust Python-based validator that handles minor whitespace mismatches.
- [ ] **Architect Mode**:
    - Inject a `<thinking>` requirement into the system prompt.
    - The agent must output its plan before attempting any file edits.
- [ ] **Diagnostic Loop**:
    - Improve `run_shell` to capture and parse `stderr`.
    - Automatically feed compiler/test errors back to the agent for "Self-Correction" loops.

---

## 🔴 Phase 4: The "UX Polish" (TUI & Distribution)
**Goal**: Professional-grade interface and one-command installation.

- [ ] **Collapsible Thinking**: Update the TUI to hide/show the `<thinking>` blocks to keep the terminal clean.
- [ ] **Multi-Step Progress**: Implement a visual "Step-by-Step" tracker for complex multi-tool plans.
- [ ] **Final Packaging**: Update `pyproject.toml` and `install.sh` for the v3 release.

---

## 📅 Estimated Timeline (1-2 Weeks)

| Phase | Duration | Key Milestone |
| :--- | :--- | :--- |
| **Phase 1** | 2 Days | Winner of "Battle of the Brains" announced. |
| **Phase 2** | 3 Days | Search tool functional and context window optimized. |
| **Phase 3** | 4 Days | Patch-based editing stable; Auto-correction loop active. |
| **Phase 4** | 2 Days | TUI finalized and master branch merge. |

---

## 🚀 Baseline Specs (RTX 3060 / 6GB)
*   **Model Size Target**: 3B - 4B (Q4_K_M)
*   **Context Target**: 64k (Q8 KV Cache)
*   **Performance Target**: >40 Tokens/Sec (Prefill-cached)
