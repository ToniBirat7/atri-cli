# Model Dossier: Gemma 4 e2b
**Role**: Current Baseline & Efficiency Specialist (2B)

## 1. llama.cpp Support & Optimization
*   **Quantization**: `Q8_0` (Highly Recommended). At 2B parameters, you can afford full 8-bit quantization with zero speed penalty, providing the best possible reasoning for its size.
*   **Flash Attention**: Fully supported.
*   **Inference**: Best-in-class latency. Ideal for small, iterative edits.
*   **GPU Offload**: `-ngl 28`.

## 2. Prompt Template (Gemma Turn)
Uses the turn-based structure inherited from Gemma 2.
```text
<start_of_turn>user
{query}<end_of_turn>
<start_of_turn>model
<thought>
{reasoning}
</thought>
{response}<end_of_turn>
```

## 3. System Prompt Best Practices
*   **Direct Instruction**: Avoid "preamble" text. Start directly with the mission and constraints.
*   **Markdown Purity**: Responds exceptionally well to tables and bulleted lists for technical specs.
*   **Roleplay Isolation**: Does not require a "Persona"; performative roles can actually degrade its technical accuracy.

## 4. Reasoning & Multi-turn Logic
*   **Native Thinking Tokens**: Gemma 4 e2b has internal tokens for `<thought>` blocks. We should utilize these rather than simulated text blocks.
*   **Constraint Adherence**: Very high. If told "Never use Python 2.7," it will comply strictly across long sessions.

## 5. Tool Calling Support
*   **Format**: Direct JSON or Function Call tags.
*   **Request Syntax**:
    ```text
    call:read_file(path="v3_roadmap.md")
    ```
*   **Reliability**: Occasional "Chain-Drift" in long sessions where it might forget to close a tool tag. Requires a state-aware orchestrator.

## 6. Context Performance (128k+)
*   **Extreme High Context**: Because the model is small, it can handle **128k context on 6GB VRAM** while still leaving room for other processes. This makes it a great "Log Auditor."
*   **RoPE Frequency**: Native scaling.
