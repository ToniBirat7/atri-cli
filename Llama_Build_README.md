# **Background: Why the CUDA Toolkit and NVCC are Essential for Your GPU**

To understand how llama.cpp leverages your `GPU` and `CPU`, you need to distinguish between the **Compiler (Build-time)** and the **Libraries (Runtime)**.

On Arch-based systems like `Arch`, the package manager provides these in a consolidated way, but they serve very different roles in the lifecycle of your LLM server.
---

## **The Components: What they are and Why they matter (Prerequesities for Optimal Llama.cpp)**

### **CUDA Toolkit (The Foundation)**
*   **What it is:** A comprehensive development environment for creating high-performance GPU-accelerated applications.
*   **Why it’s required:** It provides the "Map" and the "Rules" for how a C++ program (like `llama.cpp`) should talk to an NVIDIA GPU.
*   **Required for:** **Build & Server.** You need the headers to build the program and the core logic to run it.

### **NVCC: NVIDIA CUDA Compiler (The Translator)**
*   **What it is:** The specialized compiler driver that sits on top of `gcc`. 
*   **Why it’s required:** `llama.cpp` contains files written in `.cu` (CUDA C++). A standard CPU compiler like `gcc` or `clang` cannot read these files. **NVCC** takes that code and "translates" it into machine code (PTX) specifically optimized for your RTX 3060’s Ampere architecture.
*   **Required for:** **Build Only.** Once the code is compiled into an executable (the `llama-server` binary), you no longer need the compiler to run the model.

### **cuBLAS / CUDA Runtime (The Math Engine)**
*   **What it is:** Highly optimized libraries for "Linear Algebra" (Matrix multiplication). 
*   **Why it’s required:** LLMs like Gemma 4 are essentially billions of matrix multiplications. These libraries are hand-tuned by NVIDIA engineers to make these calculations happen as fast as physically possible on your hardware.
*   **Required for:** **Server (Runtime).** This is the "engine" that powers the generation of every word/token.

### **cuDNN: CUDA Deep Neural Network library (The Optimizer)**
*   **What it is:** A GPU-accelerated library of primitives for deep neural networks.
*   **Why it’s required:** While `llama.cpp` is highly self-reliant, `cuDNN` provides specialized tuning for the "tensors" (data structures) used in modern AI models. It helps in optimizing memory layout and throughput.
*   **Required for:** **Server (Runtime).** It ensures the data moves through your GPU's VRAM without bottlenecks.

```bash

sudo pacman -S git base-devel cmake cuda cudnn nvidia-utils

```

### **CMake: The Architect**

**What is it?**  
CMake is a **Build System Generator**. It is not a compiler. Think of it as the **Architect** who draws the blueprints. It coordinates your "construction workers"—the CPU compiler (**gcc**) and the GPU compiler (**nvcc**)—to ensure they work together to build the final program.

**Why is it required for `llama.cpp`?**  
`llama.cpp` is a complex project that can run on many different types of hardware. CMake looks at your specific system (Ryzen 6600H + RTX 3060) and your OS (Omarchy/Arch) to:
1.  **Locate Tools:** Automatically find the CUDA Toolkit in `/opt/cuda`.
2.  **Handle Complexity:** Decide which parts of the code should be built for the CPU and which for the GPU.
3.  **Automate Commands:** Replace thousands of lines of manual compiler commands with a single automated process.

**Build vs. Server?**  
*   **Required for: Build Only.**  
*   Once the `llama-server` binary is created, CMake is no longer needed. You can delete it or ignore it; it is not used while you are chatting with the AI.

**The Essential Flags for your RTX 3060:**  
*   **`-B build`**: Directs all "construction mess" (temporary files) into a dedicated folder.
*   **`-DGGML_CUDA=ON`**: The "Master Switch" that tells CMake to enable NVIDIA GPU acceleration.
*   **`-DCMAKE_CUDA_ARCHITECTURES=86`**: The "Precision Flag." It tells the compiler to optimize specifically for **Ampere** (30-series) chips, unlocking maximum speed for your 3060.

| Component        | Role                                 | Required for Build? | Required for Server? |
| :--------------- | :----------------------------------- | :-----------------: | :------------------: |
| **CMake**        | **Architect** (Generates blueprints) |       **Yes**       |          No          |
| **NVCC**         | **GPU Compiler** (Builds GPU code)   |       **Yes**       |          No          |
| **CUDA Toolkit** | **Library** (Math & GPU logic)       |       **Yes**       |       **Yes**        |

---
--- 

# **Llama Setup Best Practices: Optimizing for Performance and Efficiency**

## **1. Clone the Repository**

```bash
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
```

---

## **2. Build the Project with Optimizations for Your Hardware**

To get the most performance out of your **RTX 3060 (Ampere)** and **Ryzen 6600H (Zen 3+)**, you must go beyond a standard build. This optimized command ensures the software speaks the "native language" of your specific chips.

### **The Optimized Build Process**

Run these commands in order inside your `llama.cpp` folder:

```bash
# 1. Clean start (removes old, non-optimized blueprints)
rm -rf build

# 2. Generate Optimized Blueprints
cmake -B build \
  -DGGML_CUDA=ON \
  -DCMAKE_CUDA_ARCHITECTURES=86 \
  -DGGML_NATIVE=ON \
  -DGGML_FLASH_ATTN=ON \
  -DGGML_CUDA_FA_ALL_QUANTS=ON

# 3. Compile the Binary
cmake --build build --config Release -j $(nproc)

# 4. Check the version to confirm it was built correctly
./build/bin/llama-cli --versions
```

---

### **Detailed Flag Breakdown**

#### **1. GPU Optimization (The Speed)**
*   **`-DGGML_CUDA=ON`**: 
    *   **What:** The "Master Switch" for NVIDIA.
    *   **Why:** Without this, your RTX 3060 sits idle. This tells the code to use CUDA cores for math.
*   **`-DCMAKE_CUDA_ARCHITECTURES=86`**: 
    *   **What:** Targets the **Ampere** architecture specifically. 
    *   **Why:** Architecture "86" is the code for the 30-series GPUs. It unlocks hardware-level instructions that generic builds miss, resulting in faster token generation.

#### **2. CPU Optimization (The Efficiency)**
*   **`-DGGML_NATIVE=ON`**: 
    *   **What:** Auto-detects your Ryzen 6600H.
    *   **Why:** Since your model is 17GB and your VRAM is 6GB, much of the model stays in system RAM. This flag enables **AVX2** and **FMA** instructions, making the "CPU-side" of the model work significantly faster.

#### **3. Memory Optimization (The Capacity)**
*   **`-DGGML_FLASH_ATTN=ON`**: 
    *   **What:** Enables **Flash Attention**.
    *   **Why:** Standard attention uses huge amounts of memory as your conversation gets longer. Flash Attention is a mathematical shortcut that uses far less VRAM and speeds up processing of long texts.
*   **`-DGGML_CUDA_FA_ALL_QUANTS=ON`**: 
    *   **What:** Forces Flash Attention to work with quantized files (like your `.gguf`). Normally, Flash Attention only works with high-precision data (F16). This flag tells the compiler to build specialized CUDA kernels that can handle "Quantized KV Caches" (like Q8_0 or Q4_0). We can set the quantization level for the `KV Cache` by using `--ctk q8_0` and `--ctv q8_0` when running the server.
    *   **Why:** By default, Flash Attention sometimes only works on high-precision models. This ensures it works on your compressed Q4 model.

#### **4. Execution (The Power)**
*   **`-j $(nproc)`**: 
    *   **What:** Use all available "Jobs."
    *   **Why:** It tells the compiler to use all **12 threads** of your Ryzen 6600H to build the program. This reduces compilation time from minutes to seconds.

Now,

The reason we use so many flags is the difference between **"just running the `build`"** and **"running optimally with `multiple build flags`"** 

If you use a basic build command with no flags, the compiler is forced to be **conservative**. It creates a program that works on *every* computer from the last 15 years. This "one-size-fits-all" approach is safe, but it’s incredibly slow for a modern machine like yours.

Here is why building for your specific device with flags is mandatory for a good experience:

### 1. The "Lowest Common Denominator" Problem
If you don't use flags like `-DGGML_NATIVE=ON`, the compiler assumes your CPU is a generic old processor. It will **not** use the high-speed math lanes (`AVX2`/`FMA`) built into your Ryzen 6600H.
*   **Without Flags:** The CPU does math one number at a time (like a person doing long division).
*   **With Flags:** The CPU does "Vector Math"—it processes 8 or 16 numbers in a single clock cycle. It's like the difference between a one-lane road and an 8-lane highway.

### 2. The GPU "Identity" Problem
Your RTX 3060 has **Tensor Cores**—specialized hardware specifically designed for AI. 
*   **Without Flags:** `llama.cpp` might use the GPU for basic calculations but won't know how to talk to the Tensor Cores.
*   **With `-DCMAKE_CUDA_ARCHITECTURES=86`:** You are telling the program: *"I have an Ampere chip. Use the 30-series specialized shortcuts."* This can literally double your speed (tokens per second).

### 3. Feature Activation (Flash Attention)
Some features are so complex they aren't "on" by default because they require specific hardware. 
*   **Without Flags:** As your conversation gets longer, the model will slow down and eventually crash because it runs out of memory.
*   **With `-DGGML_FLASH_ATTN=ON`:** You enable a mathematical algorithm that compresses the "memory" of the conversation. This is the only way to use Gemma 4's massive context window on a 6GB VRAM card without it slowing to a crawl.

---

## **3. Download `GGUF` Models**

### **Understanding GGUF & Quantization**

To use models in `llama.cpp`, you need them in **GGUF** format. Here is why this format exists and how it differs from the standard files you see on HuggingFace.

---

### **1. What is GGUF?**
**GGUF (GPT-Generated Unified Format)** is a binary file format designed specifically for fast inference. It stores everything—the model's "brain" (weights) and its "instructions" (metadata/config)—inside a **single file**.

### **2. GGUF vs. Safetensors**
| Feature       | Safetensors                                 | GGUF                                 |
| :------------ | :------------------------------------------ | :----------------------------------- |
| **Purpose**   | Training & Fine-tuning                      | **Inference (Running the model)**    |
| **Software**  | Python, PyTorch, Transformers               | **llama.cpp**, Ollama, LM Studio     |
| **Hardware**  | Optimized for full GPU VRAM                 | Optimized for **GPU + CPU (Hybrid)** |
| **Structure** | Multiple files (config, weights, tokenizer) | **One single file** (`.gguf`)        |

**Why do we need GGUF for `llama.cpp`?**  
`llama.cpp` is written in C++. It cannot natively read Python-based `safe.tensors`. GGUF allows `llama.cpp` to **Memory Map (mmap)** the model, which means it can load the file almost instantly and share it between your 32GB RAM and 6GB VRAM efficiently.

---

### **3. What is Quantization?**
Quantization is the process of "compressing" the model weights. Think of it like converting a high-resolution 4K video into a high-quality 1080p file: it’s much smaller, but looks almost identical.

*   **Original Model (BF16/F16):** Uses 16 bits per weight. For a 26B model, this would require **~52GB** of RAM (You couldn't run it).
*   **Quantized Model (Q4_K_M):** Uses ~4 bits per weight. This shrinks the model to **~17GB**, allowing it to fit in your 32GB RAM comfortably.

---

### **4. The Best Quants for Your Device**
Since you have 32GB of RAM and a 6GB RTX 3060, here are the "Sweet Spots":

1.  **Q4_K_M (The Gold Standard):** 
    *   **Description:** Recommended for most users. 
    *   **Balance:** High speed, low memory, and **99% intelligence** retention.
2.  **UD-Q4 (Unsloth Dynamic):**
    *   **Description:** The version you are downloading. 
    *   **Advantage:** It uses "Dynamic" bits—higher quality for important logic layers and lower for easy ones. It's the "smartest" 4-bit version.
3.  **Q5_K_M / Q6_K:**
    *   **Description:** Larger and slower. 
    *   **Use case:** Only if you are doing highly sensitive medical or legal coding where every tiny bit of accuracy matters. (Not recommended for 6GB VRAM).

---

## **4. Run the Server with Optimal Flags**

After successfully compiling `llama.cpp`, your folder is no longer just a collection of code—it is now a powerful AI workstation. Here is the background on what was created and the optimal way to launch your server.

### 1. Background: What happened after the build?

When you ran the `cmake` commands, the compilers transformed thousands of lines of C++ and CUDA code into **binary executables**. 

*   **Where are they?** Everything you need is now in `llama.cpp/build/bin/`.
*   **The Key Artifacts:**
    *   `llama-server`: This is your primary tool. It turns your laptop into an AI host with a web-based chat interface.
    *   `llama-cli`: A command-line tool for chatting directly in the terminal.
    *   `llama-quantize`: A tool used if you ever want to compress your own models.
*   **The Library:** Inside `build/bin/`, you'll also find shared libraries that allow the software to talk to your RTX 3060.

Now that the "engine" is built and the "fuel" (GGUF models) is in the `models/` folder, we need to start the engine with the most efficient settings.

---

### 2. The Optimal Server Command

For your **6GB VRAM** and **32GB RAM** setup, the goal is to maximize the GPU's speed without crashing the memory. This command uses **KV Cache Quantization** and **Flash Attention** to give you a massive context window (16k tokens) that would normally be impossible on a 6GB card.

Run this from the `llama.cpp` root directory:

```bash
# Enable Unified Memory spillover support
export GGML_CUDA_ENABLE_UNIFIED_MEMORY=1

./build/bin/llama-server \
  -m /run/media/tonibirat/TOSHIBA_EXT/Gemma4_MoE_Models/gemma-4-26B-A4B-it-UD-Q4_K_M.gguf \
  --mmproj /run/media/tonibirat/TOSHIBA_EXT/Gemma4_MoE_Models/gemma-4-26b/mmproj-BF16.gguf \
  --n-gpu-layers 22 \
  --ctx-size 16384 \
  --ctk q8_0 \
  --ctv q8_0 \
  --threads 6 \
  --flash-attn \
  --mlock \
  --host 0.0.0.0 \
  --port 8080
```

---

### 3. Detailed Flag Explanation (Advanced)

#### **The Memory Savers (KV Cache)**
*   **`--ctk q8_0` and `--ctv q8_0` (Cache Type Key/Value):** 
    *   **What:** This quantizes the "Memory" (KV Cache) of your current conversation to 8-bit.
    *   **Why:** It cuts the VRAM required for the context window in half. This is why you can use 16k context instead of only 8k.

*   **`--ctk turbo4` and `--ctv turbo3` (Alternative):** 
    *   **What:** These are "Turbo" quantization modes that use a mix of 4-bit and 3-bit quantization for the KV Cache. Google Just Released these as part of their "Gemma 4 Turbo" optimization.
    *   **Why:** They can further reduce VRAM usage, allowing for even larger context windows (up to 32k tokens) on a 6GB card, but they may slightly reduce accuracy.

*   **`--flash-attn`:** 
    *   **What:** Activates the Flash Attention kernels you built.
    *   **Why:** It makes the math significantly more efficient and prevents the "slowdown" that usually happens when you reach the end of a long chat.

#### **The Hardware Optimizers**
*   **`--n-gpu-layers 22`:** 
    *   **What:** Offloads 22 layers of the model's "brain" to the RTX 3060.
    *   **Why:** 22 is the "Safe Zone" for 6GB VRAM. It leaves enough room for the vision model (`mmproj`) and the KV cache.
*   **`--threads 6`:** 
    *   **What:** Uses 6 physical cores of your Ryzen 6600H.
    *   **Why:** For LLMs, using physical cores is faster than using all 12 virtual threads. 6 is your "magic number" for speed.
*   **`--mlock`:**
    *   **What:** Pins the model in your 32GB RAM.
    *   **Why:** It prevents the Linux kernel from "swapping" the model to your SSD, ensuring the model never lags or stutters during a response.

#### **MoE Models Best Split**

> Keep the small fast firing "expert" layers on the GPU, while keeping the giant sleeping `Experts` layers on the CPU. This allows you to take advantage of the GPU's speed for the most computationally intensive parts of the model, while still being able to run the entire model on a system with limited VRAM.

For this we've to use `--n-gpu-layers 999` and `--n-cpu-moe number_of_experts`. Take every layer of experts and pin them to the CPU, while the rest of the model runs on the GPU. This way, we can leverage the GPU's speed for the non-expert layers, while still being able to run the entire model on a system with limited VRAM.

> Use `--no-mmap` flag when running `MoE` models with `llama.cpp`. This prevents the model from being memory-mapped, which can cause performance issues when running on CPU. By disabling memory mapping, the model will be loaded into RAM instead of disk, allowing for faster access and improved performance.

> `--ctk turbo4` and `--ctv turbo3` flags can be used to enable "Turbo" quantization modes for the KV Cache. These modes use a mix of 4-bit and 3-bit quantization to further reduce VRAM usage, allowing for even larger context windows (up to 32k tokens) on a 6GB card. However, they may slightly reduce accuracy, so it's important to test and evaluate the performance of your model with these settings to find the right balance between speed and accuracy for your specific use case. 

- `Turbo Quant` uses `Group Query Attention` (GQA) with `8:1` ratio, `Keys` can take heavier quantization than `Values` and `Queries` because they are only used for lookup, while `Values` and `Queries` are used for the actual computation. This allows for more aggressive quantization of the `Keys`, which can significantly reduce VRAM usage without a significant loss in accuracy.

- With this we can increase the context window to `32k` tokens on a `6GB` card, which is a significant improvement over the standard `4k` token limit. This allows for much longer conversations and more complex interactions with the model, making it more suitable for applications like chatbots and virtual assistants that require a large context window to maintain coherence and provide accurate responses.

#### **The Safety Net**
*   **`export GGML_CUDA_ENABLE_UNIFIED_MEMORY=1`**:
    *   **What:** Allows the GPU to "borrow" system RAM.
    *   **Why:** If a complex image or long text temporarily exceeds 6GB, your computer won't crash; it will just slow down slightly until the GPU is clear again.

---

### 4. How to use it
1.  **Run the command.**
2.  Watch the terminal logs. You should see:
    *   `llm_load_tensors: offloaded 22/XX layers to GPU`
    *   `flash_attn = 1`
    *   `KV self_size = 1024.00 MB` (This is small thanks to `q8_0`!)
3.  **Open Browser:** Go to `http://localhost:8080`.
4.  **Test Vision:** Drag an image into the chat and ask Gemma-4, *"What is in this image?"*

--- 

## **5. How to Research Instruction Manual for any Models**

Finding the correct "instruction manual" for an LLM is critical. If you use the wrong format, a brilliant model will act like a broken one.

Here is the definitive guide on where to find prompting schemas, tool-calling formats, and reasoning patterns for any model.

---

### 1. The "Source of Truth": Hugging Face `tokenizer_config.json`
Every model on Hugging Face has a file that contains the exact mathematical template the model was trained on.

*   **Where to look:** Go to the model's Hugging Face page $\rightarrow$ Click the **"Files and versions"** tab $\rightarrow$ Open **`tokenizer_config.json`**.
*   **What to find:** Look for the `"chat_template"` field. 
    *   It will look like a piece of code (Jinja2). 
    *   Example: For Gemma, it will show tags like `<start_of_turn>user\n...`.
    *   **Why it's best:** This is the most accurate source. It tells you exactly how the model expects the **System Prompt**, **User Prompt**, and **Assistant Response** to be wrapped.

### 2. The Model Card (The "ReadMe")
Most reputable creators (Google, Meta, Mistral, Unsloth) include a "Prompting" section on the main page of the model.

*   **Search for:** Keywords like **"Prompt Template"**, **"Instruction Format"**, or **"Chat Format"**.
*   **Common Formats:**
    *   **ChatML:** (Used by OpenAI, Hermes, Qwen) uses `<|im_start|>system\n...`.
    *   **Llama-3:** Uses `<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n...`.
    *   **Gemma:** Uses `<start_of_turn>user\n...`.

### 3. Tool Calling & Function Schemas
Tool calling is newer and more sensitive. Most models expect tools to be defined in the **System Prompt** as a JSON schema.

*   **Where to search:**
    1.  **Model Documentation:** Check if the model has a "Function Calling" section (e.g., Mistral-7B-v0.3 or Llama-3.1).
    2.  **Berkeley Function Calling Leaderboard (BFCL):** A great site to see which prompts work best for specific models.
    3.  **Llama.cpp Grammars:** In your `llama.cpp` folder, look at the `grammars/` directory. These `.gbnf` files force the model to output valid JSON for tool calling.

### 4. Reasoning (Chain of Thought)
If you want the model to "think" before it answers (like DeepSeek-R1 or O1), the formatting is usually handled by the **System Prompt**.

*   **Best Practice:** Use a "Thinking Trigger." 
    *   *System Prompt:* "You are a reasoning assistant. Always analyze the problem step-by-step inside `<thought>` tags before providing the final answer."
*   **Where to find strategies:**
    *   **Prompt Engineering Guide (promptingguide.ai):** This is the "Bible" of prompting. It covers Zero-shot, Chain-of-Thought (CoT), and ReAct patterns for all models.

### 5. Community Hubs (The "Real-World" Testing)
Sometimes the official documentation isn't the best for the *quantized* (GGUF) versions.

*   **Reddit /r/LocalLLaMA:** Search for "[Model Name] prompt template." Users often post "Aha!" moments where they find a specific format that works better than the official one.
*   **Unsloth Documentation:** Since you are using an Unsloth model, their [official blog](https://unsloth.ai/blog) and GitHub often provide optimized prompt templates for Gemma and Llama models that they have fine-tuned.

---

### Summary Checklist for a New Model:
1.  **Check Hugging Face:** Look for `tokenizer_config.json` for the raw tags.
2.  **Check `llama.cpp` Logs:** When you start `llama-server`, it usually tries to **auto-detect** the template. Look for a line saying `Chat template: [Name]`.
3.  **Search "Prompting Guide":** Go to [PromptingGuide.ai](https://www.promptingguide.ai/) for high-level logic (Reasoning/Tool use).
4.  **Try ChatML first:** If you can't find anything, many modern models are being fine-tuned to understand **ChatML** as a universal language.