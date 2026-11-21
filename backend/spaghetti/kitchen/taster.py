"""👅 Taster: scores the dish. Cheap overlap check (Rust) + an LLM judge. Honest about its limits."""
import json
import re

from ..domain.models import Verdict
from ..runtimes.base import ModelError
from .thinking import split_thinking

PROMPT = (
    "ROLE:TASTER You grade an answer against pantry excerpts. Reply with ONLY JSON: "
    '{"score": 0-10, "issues": "one short sentence"}. 10 = every claim is supported by the excerpts.'
)


class Taster:
    def __init__(self, llm, model, engine):
        self.llm, self.model, self.engine = llm, model, engine

    def taste(self, question, answer, hits, careful: bool = False) -> Verdict:
        context = "\n".join(h.text for h in hits)
        grounded = self.engine.overlap(answer, context)
        if not careful:  # fast check: Rust word-overlap, no extra model call
            return Verdict(round(grounded * 10, 1), grounded, "", "fast-overlap")
        try:
            raw = self.llm.chat(
                [{"role": "system", "content": PROMPT},
                 {"role": "user", "content": f"{context}\nQUESTION: {question}\nANSWER: {answer}"}],
                self.model,
            )
            raw, _ = split_thinking(raw)
            data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
            score = max(0.0, min(10.0, float(data["score"])))
            return Verdict(score, grounded, str(data.get("issues", ""))[:200], "taster-llm")
        except (ModelError, AttributeError, ValueError, KeyError, TypeError):
            # The judge failed or spoke gibberish: fall back to the plain overlap number.
            return Verdict(round(grounded * 10, 1), grounded, "Judge unavailable; used word overlap.", "overlap-only")
