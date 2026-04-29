# v3 Active Task Tracker

## 🟢 Phase 1: The "Battle of the Brains" (In Progress)
- [x] **Research model templates** for Qwen 2.5, Llama 3.2, and Gemma 4.
- [ ] **Create benchmark scripts** to test "Search-Replace" block compliance.
- [ ] **Execute Benchmark 1**: Gemma 4 e2b (Baseline).
- [ ] **Execute Benchmark 2**: Gemma 4 E4B.
- [ ] **Execute Benchmark 3**: Llama 3.2 3B.
- [ ] **Execute Benchmark 4**: Qwen 2.5 Coder 3B.
- [ ] **Analyze Results** and pick the v3 primary engine.

## 🔵 Phase 2: The "Semantic Core"
- [ ] Setup SQLite-vec environment.
- [ ] Implement file watcher and indexing logic.
- [ ] Integrate llama.cpp prefix caching in orchestrator.

## 🟡 Phase 3: The "Architect" Engine
- [ ] Design and implement `search_replace_edit` tool.
- [ ] Update System Prompt for `<thinking>` enforcement.
- [ ] Implement `stderr` feedback loop for `run_shell`.

## 🔴 Phase 4: UX & Polish
- [ ] TUI: Collapsible reasoning blocks.
- [ ] TUI: Multi-step plan visualizer.
- [ ] Merge to master.
