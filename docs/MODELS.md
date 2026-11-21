# 🧠 Models

Ollama only; the menu stops at **3B** so models fit and run fast on ordinary laptops. Tags and sizes were checked against the Ollama library.

| Model | Download | Notes |
|---|---|---|
| Qwen3 0.6B | 0.5 GB | tiny, thinking |
| Gemma 3 1B | 0.8 GB | light writing |
| Llama 3.2 1B | 1.3 GB | fast chat |
| Qwen3 1.7B | 1.4 GB | thinking |
| Qwen2.5 3B | 1.9 GB | reasonable answers |
| Llama 3.2 3B | 2.0 GB | best all-rounder |

**Default pick** (`recommend_default`): the largest model whose memory estimate (download × 1.2 + 0.8 GB) is ≤ 70% of the budget, where budget = max(90% of VRAM, 65% of RAM). If nothing fits, the smallest. This is a rule of thumb, not a benchmark.

**Other models:** any model you already pulled in Ollama appears under "On this device" and works. Only the menu models can be downloaded from the UI, and the setup script only ever contains menu tags (no user text reaches a shell).

**1-bit models (BitNet):** not included. The only Ollama-compatible build is a community GGUF and the speed gains need Microsoft's `bitnet.cpp`; we could not verify it, so it is left out rather than listed untested.

**Thinking models** (Qwen3): `<think>` blocks are streamed into a collapsible "Thought process", even when the tag is split across network chunks.
