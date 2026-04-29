# Model Dossier: Gemma 4 E4B
**Role**: Enhanced Reasoning & Architect Specialist (4B)

## 1. llama.cpp Support & Optimization
*   **Quantization**: `Q4_K_M` (Optimal). At 4B, the memory footprint is ~2.8GB, leaving exactly enough room for a 64k Q8 KV cache on your 6GB card.
*   **Reasoning Effort**: Optimized for high `reasoning_effort` parameters in `llama.cpp`.
*   **VRAM Usage**: ~3.2GB at 32k context.
*   **GPU Offload**: `-ngl 32`.

## 2. Prompt Template (Gemma Turn - Extended)
Shares the Gemma 4 dialect but supports more complex turn structures.
```text
<start_of_turn>user
{query}<end_of_turn>
<start_of_turn>model
<thought>
{detailed_architectural_plan}
</thought>
{tool_calls_or_response}<end_of_turn>
```

## 3. System Prompt Best Practices
*   **Architectural Steering**: Instruct the model to "Validate all imports and dependency chains before proposing a change."
*   **Multi-Step Planning**: Encourage the model to output a 3-step plan in its thought block.
*   **Schema Enforcement**: Provide the full project folder structure in the system prompt to leverage its high-density reasoning.

## 4. Reasoning & Multi-turn Logic
*   **Deep Reasoning Tokens**: Specifically trained for long-form planning.
*   **State Tracking**: Superior to the `e2b` variant in tracking "Ghost States" (variables defined in one file but used in another).

## 5. Tool Calling Support
*   **Format**: XML or JSON.
*   **Request Syntax**:
    ```xml
    <call:patch_file path="utils.py">
    { "search": "old_code", "replace": "new_code" }
    </call:patch_file>
    ```
*   **Reliability**: The most reliable of the Gemma family for complex, multi-argument tool calls.

## 6. Context Performance (64k - 96k)
*   **The "6GB Limit"**: On your RTX 3060, this model caps out comfortably at **64k context**. Pushing to 128k will cause "Context Spillage" into System RAM, slowing it down.
*   **Recommendation**: Use a 64k window for high-speed coding and swap to `e2b` for 100k+ log analysis.
