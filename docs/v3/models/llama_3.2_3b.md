# Model Dossier: Llama 3.2 3B
**Role**: High-Speed Generalist & Router

## 1. llama.cpp Support & Optimization
*   **Quantization**: `Q5_K_M` (Recommended). Llama 3.2 3B is highly efficient; the 5-bit version provides near-FP16 reasoning quality for a minor VRAM increase.
*   **Flash Attention**: Supported and recommended.
*   **Throughput**: Fastest in its class. Expect 70+ tokens/sec on RTX 3060.
*   **GPU Offload**: `-ngl 28` (Full offload).

## 2. Prompt Template (Llama 3 Header)
Uses the specialized Llama 3 metadata headers.
```text
<|begin_of_text|><|start_header_id|>system<|end_header_id|>

{system_prompt}<|eot_id|><|start_header_id|>user<|end_header_id|>

{query}<|eot_id|><|start_header_id|>assistant<|end_header_id|>
```

## 3. System Prompt Best Practices
*   **Explicit Persona**: Responds well to defined roles (e.g., "You are an expert Linux Systems Engineer").
*   **Few-Shot Requirement**: For complex tools, Llama 3.2 3B requires 2-3 examples of the tool output format to avoid formatting errors.
*   **Negative Constraints**: Use clear "DO NOT" instructions (e.g., "Do not output conversational filler").

## 4. Reasoning & Multi-turn Logic
*   **Logic Consistency**: Excellent at mathematical and logical deduction.
*   **Instruction Following**: High compliance with specific output formats (e.g., "Output exactly 3 bullet points").

## 5. Tool Calling Support
*   **Format**: JSON-in-Markdown or Raw JSON.
*   **Request Syntax**:
    ```json
    {
      "tool": "run_shell",
      "parameters": {"command": "ls -la"}
    }
    ```
*   **Reliability**: May require a "Format Guard" (regex or schema validation) to ensure the JSON is not wrapped in unnecessary text.

## 6. Context Performance (128k)
*   **Scaling**: Native 128k support. Very stable at long contexts.
*   **Memory Tip**: If using Llama 3.2 as a "Reviewer" for large logs, keep the temperature low (0.1) to maintain focus across the full 128k window.
