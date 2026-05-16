## **llama.cpp**

`llama.cpp` is a C/C++ library designed for high performance inference of Large Language Models (LLMs) with minimal steps. Research more about how it does in detail. 

It utilizes advanced quantization techniques to drastically reduce the memory footprint of models, allowing large models to run on hardware with limited `VRAM`.

It introduces the `GGUF` file format, which stores all necessary model metadata, weights, and tokenizer information in a single portable file.

It includes a built-in-HTTP server that provides a `OpenAI-Compatible API`, allowing it to serve as a drop-in replacement for applications built on OpenAI's infrastructure.

> It is significantly faster than Python based frameworks like `PyTorch` for inference especially on `CPU` only setups. 

> To run models in CPU using `llama.cpp`, the CPU needs to support the `AVX2`, `FMA`, and `F16C` (Instruction Set Architecture)

> Runs everywhere (Windows, Linux, macOS), we've control over the memory for running the model (CPU or GPU or Split)

> We can convert models from `PyTorch`, `HuggingFace` format to `GGUF` format using `convert.py` script provided by `llama.cpp`. This allows us to take advantage of the performance benefits of `llama.cpp` while still using models that were originally trained in other frameworks.

> If possible always try to use `MoE` (Mixture of Experts) family of models with `llama.cpp` as they are optimized for inference and can run efficiently on CPU. Offload the "expert" layers to the GPU if you have one, while keeping the rest on CPU. This can provide a significant boost in performance without requiring a high-end GPU.

<hr>
<hr>

## **`MoE` (Mixture of Experts) Models Best Practice**

> Keep the small fast firing "expert" layers on the GPU, while keeping the giant sleeping `Experts` layers on the CPU. This allows you to take advantage of the GPU's speed for the most computationally intensive parts of the model, while still being able to run the entire model on a system with limited VRAM.

For this we've to use `--n-gpu-layers 999` and `--n-cpu-moe number_of_experts`. Take every layer of experts and pin them to the CPU, while the rest of the model runs on the GPU. This way, we can leverage the GPU's speed for the non-expert layers, while still being able to run the entire model on a system with limited VRAM.

> Use `--no-mmap` flag when running `MoE` models with `llama.cpp`. This prevents the model from being memory-mapped, which can cause performance issues when running on CPU. By disabling memory mapping, the model will be loaded into RAM instead of disk, allowing for faster access and improved performance.

> `--ctk turbo4` and `--ctv turbo3` flags can be used to enable "Turbo" quantization modes for the KV Cache. These modes use a mix of 4-bit and 3-bit quantization to further reduce VRAM usage, allowing for even larger context windows (up to 32k tokens) on a 6GB card. However, they may slightly reduce accuracy, so it's important to test and evaluate the performance of your model with these settings to find the right balance between speed and accuracy for your specific use case. 

- `Turbo Quant` uses `Group Query Attention` (GQA) with `8:1` ratio, `Keys` can take heavier quantization than `Values` and `Queries` because they are only used for lookup, while `Values` and `Queries` are used for the actual computation. This allows for more aggressive quantization of the `Keys`, which can significantly reduce VRAM usage without a significant loss in accuracy.

- With this we can increase the context window to `32k` tokens on a `6GB` card, which is a significant improvement over the standard `4k` token limit. This allows for much longer conversations and more complex interactions with the model, making it more suitable for applications like chatbots and virtual assistants that require a large context window to maintain coherence and provide accurate responses.

> On my 6GB VRAM card, I ran `MoE` `Gemma 4-26B-A4B-it-UD-Q4_K_M.gguf` with `mmproj-BF-16` and the best setting for me was: 

```bash

# 1. Enable NVIDIA Zero-Copy Unified Memory 
export GGML_CUDA_ENABLE_UNIFIED_MEMORY=1

# 2. Launch the Max-Context / Max-Speed Server
./build/bin/llama-server \
  -m /run/media/tonibirat/TOSHIBA_EXT/Gemma4_MoE_Models/gemma-4-26B-A4B-it-UD-Q4_K_M.gguf \
  --mmproj /run/media/tonibirat/TOSHIBA_EXT/Gemma4_MoE_Models/mmproj-BF16.gguf \
  -ngl 999 \
  --n-cpu-moe 128 \
  -c 32768 \
  -np 1 \
  -ctk q4_0 \
  -ctv q8_0 \
  -fa on \
  --no-mmap \
  --mlock \
  -t 6 \
  --host 0.0.0.0 \
  --port 8080

```

- It gives 24 Tokens/s with `6` threads and `128` experts pinned to CPU, while the rest of the model runs on GPU. With 32k context window, it can handle much longer conversations without running out of VRAM. Still 1GB VRAM is left for the GPU to handle the non-expert layers, which allows for a significant boost in performance compared to running the entire model on CPU.

<hr>
<hr>

## **Important Flags with `llama.cpp`**

- `--model`: This flag specifies the path to the model file you want to use for inference. It should point to a `.gguf` file that contains the quantized model.

- `--threads`: This flag allows you to specify the number of CPU threads to use for inference. More threads can speed up processing, but it depends on your CPU's capabilities.

- `--n-gpu-layers`: This flag specifies the number of layers to offload to the GPU. If you have a compatible GPU, offloading some layers can significantly improve performance. The first `n` layers will be offloaded to the GPU, while the rest will run on the CPU.



<hr>
<hr>

## **Understaning `AVX2`, `FMA` and `F16C` for CPU**

Normally, a CPU does Scalar Processing. This means it performs one operation on one piece of data at a time. For example, "Add number A to B, then add number C to number B". This is fine for Word Documents or browsing the web, but it is too slow for AI inference. 

AI models (like Gemma 4) are essentially giant collections of `Matrices` (big tables of numbers). To generate a single word, the CPU has to perform billions of multiplications and additions. If the CPU did this one-by-one, your chatbot would take minutes to answer a single question.

To solve this, CPU manufacturers (Intel and AMD) created `SIMD` (Single Instruction, Multiple Data). This allows the CPU to perform one operation on a whole batch of numbers simultaneously.

**AVX2 (Advanced Vector Extension 2)**

- It is a set of instructions that allows the CPU to handle `wide` registers (256-bit)

- So what it does is, instead of adding two numbers together, `AVX2` allows the CPU to add `Eight` pairs of `32-bit` numbers in a `Single Clock Cycle`. 


**FMA (Fused Multiply-Add)**

- It is a specialized instruction that combines two mathematical operation into one

- In standard math, to do (A x B) + C, the FMA does the entire operation in a single step with single instruction

**F16C (Half-Precision Floating-Point Conversion)**

- A set of instructions for fast conversion between "Half Precision" (16-bit) and "Single Precision" floating-point numbers

- AI models are often stored in 16-bit (FP16) to save space, but CPUs often prefer to do the actual math in 32-bit (FP32) for precision. Converting millions of numbers from 16-bit to 32-bit is a heavy task. F16C provides a "hardware shortcut" to do this conversion almost instantly.

> Since you are using a Quantized (Q4) model, the weights are stored in a compressed 4-bit format. To do the math, llama.cpp must "dequantize" those numbers back into a floating-point format. F16C accelerates the movement and conversion of these numbers, reducing the "bottleneck" between your RAM and your CPU cores.


