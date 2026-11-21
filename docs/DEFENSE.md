# 🛡️ Design defense (honest Q&A)

Written so a fresher/intermediate developer can explain every choice in an interview.

### Why rename and rebuild MEI?
The uploaded MEI project had ~15 agent files (visual parsing, table extraction, conflict resolution, cross-encoder ranking, metadata enrichment…), ChromaDB + sentence-transformers, a 42 KB `routes.py`, three overlapping orchestrator implementations, and committed vector-DB binaries. Much of it overlapped or was hard to explain. Spaghetti keeps the **one idea worth keeping**, *evaluate before you answer*, and rebuilds it small.

| MEI | Spaghetti | Reason |
|---|---|---|
| 15 agents | 5 cooks | each has one job you can explain in a sentence |
| Chroma + embeddings (heavy install) | BM25 in Rust | zero downloads; limits are documented |
| FastAPI + uvicorn + pydantic | Python stdlib | nothing to install; fewer moving parts |
| Tailwind-style UI | plain CSS + ES modules | "no heavy frameworks" |
| 4 cloud providers + keys | offline only: browser (WebGPU) + Ollama, chosen by a device advisor | requirement |
| committed `chroma_db/`, uploads, a demo video | removed | data does not belong in git |
| Evaluation described, not reproducible | `python run.py eval` | claims must be checkable |

### Why Python + Rust?
Python is the right glue (runtimes, HTTP, orchestration). Rust takes four pure functions (chunk, BM25, overlap, hardware probe) where correctness and speed are easy to verify. The boundary is plain text on stdin/stdout, so there is no FFI to debug. If Rust is missing, a Python twin runs, and a test proves both agree.
*Honest caveat:* with a few documents the speedup is invisible. We chose it for a clean, testable boundary and to scale later.

### Why is the Head Chef rule-based, not an LLM?
Planning here is "pick a mode and a number". An LLM call would add cost, latency and randomness for no gain. If you later need richer plans, swap `HeadChef.plan`; nothing else changes.

### Why a bounded retry?
Self-correction can reinforce errors, and a judge LLM can be wrong. One retry caps cost (max 4 calls) and prevents infinite loops. The Expediter serves the best-scoring attempt, not blindly the last.

### Why BM25 and not embeddings?
Embeddings need a model download or another API and a vector DB. BM25 is ~40 lines, explainable and fast. It cannot match synonyms. The eval exposed a real failure (a stray word 'cup' answered a world-cup question); we fixed it with a coverage filter, honestly tuned on a tiny set. The pantry/engine split means you can add embeddings behind the same `rank` signature.

### Why only text files?
Parsing PDFs/images reliably needs heavy libraries and OCR. MEI included those agents but they weren't verified here. We prefer a smaller promise we can keep. Convert a PDF to text first, or add a loader in `pantry/`.

### Why remove cloud APIs?
Goal: fully offline, private, no accounts. Removing API providers deleted a whole class of risk (keys, billing, data leaving the device) and about 150 lines. The trade-off is quality: small local models are weaker than frontier cloud models, which is what the advisor, the Taster and the honest limits are for.

### Why two runtimes (browser + Ollama)?
Different users, different devices. A browser tab needs nothing installed and works on a laptop with any WebGPU GPU, but is capped to small models. Ollama uses RAM and the GPU properly and reaches 32B. The advisor starts you on whichever is ready and offers the bigger one as a level-up.

### Why vendor WebLLM instead of using a CDN?
The UI then works with no external script host and is auditable. It is a library, not a UI framework: we call two functions. Model weights still download once (from the model host) and are then cached by the browser.

### Why a Rust hardware probe?
Browsers hide real RAM (capped at 8 GB) and VRAM. A std-only Rust binary reads `/proc/meminfo`, `sysctl`, PowerShell and `nvidia-smi` without dependencies, and a Python twin keeps it working without Rust.

### Why rules of thumb for the advisor?
Real benchmarks need the user's hardware. Transparent, tested rules (see docs/ADVISOR.md) can be explained, argued with and tuned. Speed labels are estimates and are labelled as such.

### Is the one-click script safe?
It only contains tags from our menu (validated server-side), uses the official installers (`winget`, `brew`, ollama.com/install.sh) and is plain text you can read first. It is generated, not executed, unless you run `python run.py setup` and answer yes.

### What would you improve next?
1. Live benchmarks to replace the speed estimates.
2. AMD/Intel GPU detection on the server.
3. Auth + HTTPS if it ever leaves localhost.
5. PDF loader.

### What is verified vs not?
See the README table: advisor, bridge, Rust parity and UI flows are tested; real GPU inference and a real Ollama download could not be run in our sandbox.


### Why was the product reduced to one page?
Setup screens, advisors and a pantry tab were friction. Now the app auto-picks a model, documents attach in the chat, and everything else lives in one model menu. Fewer screens, less code, faster to learn.

### Why fast mode by default?
A judge call doubles latency on small local models. Rust word-overlap gives a free groundedness score; the AI judge and retry are an opt-in "Careful mode".

### Why only Ollama?
One runtime means one code path to test and explain. Ollama already handles downloads, GPU use and model storage.
