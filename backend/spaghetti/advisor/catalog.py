"""The model menu: small Ollama models only (<= 3B) so they fit and run fast on ordinary laptops.
Tags and sizes were checked against the Ollama library. Memory estimate = download size x 1.2 + 0.8 GB (context)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Model:
    tag: str
    label: str
    params_b: float
    size_gb: float
    reasoning: bool
    blurb: str

    @property
    def mem_gb(self) -> float:
        return round(self.size_gb * 1.2 + 0.8, 1)


CATALOG: tuple[Model, ...] = (
    Model("qwen3:0.6b", "Qwen3 0.6B", 0.6, 0.5, True, "Tiny thinking model."),
    Model("gemma3:1b", "Gemma 3 1B", 1.0, 0.8, False, "Light and clear writing."),
    Model("llama3.2:1b", "Llama 3.2 1B", 1.2, 1.3, False, "Fast general chat."),
    Model("qwen3:1.7b", "Qwen3 1.7B", 1.7, 1.4, True, "Small thinking model."),
    Model("qwen2.5:3b", "Qwen2.5 3B", 3.0, 1.9, False, "Reasonable answers at 3B."),
    Model("llama3.2:3b", "Llama 3.2 3B", 3.2, 2.0, False, "Best all-rounder that stays small."),
)
OLLAMA_TAGS = {m.tag for m in CATALOG}


def budget_gb(ram_gb: float, vram_gb: float) -> float:
    """Ollama can use about 65% of RAM, or 90% of dedicated VRAM, whichever is larger."""
    return max(vram_gb * 0.9, ram_gb * 0.65)


def fit(m: Model, ram_gb: float, vram_gb: float) -> str:
    b = budget_gb(ram_gb, vram_gb)
    return "comfortable" if m.mem_gb <= b * 0.7 else "tight" if m.mem_gb <= b else "no"


def recommend_default(ram_gb: float, vram_gb: float = 0.0) -> str:
    """Largest model that fits comfortably; the smallest one if nothing does."""
    ok = [m for m in CATALOG if fit(m, ram_gb, vram_gb) == "comfortable"]
    return max(ok, key=lambda m: m.params_b).tag if ok else min(CATALOG, key=lambda m: m.params_b).tag
