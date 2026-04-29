# Model Dossier: Qwen 2.5 Coder 3B
**Role**: Primary v3 Coding & Patching Engine

## 1. llama.cpp Support & Optimization
*   **Quantization**: `Q4_K_M` (Recommended for RTX 3060 / 6GB). Provides ~50 t/s generation speed with negligible logic loss.
*   **Flash Attention**: **MANDATORY** (`--flash-attn`). Essential for maintaining performance beyond 8k context.
*   **KV Cache**: Use `-ctk q8_0 -ctv q8_0` for 64k+ context. If VRAM pressure increases, drop to `q4_1` for cache quantization.
*   **GPU Offload**: `-ngl 32` (Offload all layers). 3B models fit entirely in 6GB VRAM.

## 2. Prompt Template (ChatML)
Qwen 2.5 utilizes the strict ChatML dialect. Failure to use correct tokens will result in "Turn Flattening" and hallucinated role-play.
```text
<|im_start|>system
{system_prompt}<|im_end|>
<|im_start|>user
{query}<|im_end|>
<|im_start|>assistant
```

## 3. System Prompt Best Practices
*   **Format over Prose**: Qwen responds better to Markdown-formatted requirements than conversational instructions.
*   **Tool Authorization**: Explicitly list available tools in a structured JSON schema within the system block.
*   **Architect Constraint**: Force the model to output a `<thought>` block before any `<tool_call>`.

## 4. Reasoning & Multi-turn Logic
*   **Recursive Problem Solving**: Qwen 2.5 has high "State Retention." It can track variables and file-system states across 10+ turns without drifting.
*   **Chain-of-Thought**: Native support for hidden reasoning. If using a `thought` block, instruct the model: "Reason about the architectural implications before proposing a patch."

## 5. Tool Calling Support
*   **Format**: XML-Style Tags (Native to Qwen).
*   **Request Syntax**:
    ```xml
    <tool_call>
    {"name": "patch_file", "arguments": {"path": "main.py", "diff": "..."}}
    </tool_call>
    ```
*   **Reliability**: Ranked #1 in 3B-class models for JSON schema adherence.

## 6. Context Performance (128k)
*   **Rope Scaling**: Uses YaRN. Ensure `--rope-freq-base 1000000` is set if using non-scaled GGUFs.
*   **Throughput**: Expect 45-60 tokens/sec on RTX 3060 for generation, and ~1200 tokens/sec for prefill.
