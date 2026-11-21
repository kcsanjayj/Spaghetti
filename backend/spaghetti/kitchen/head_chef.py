"""👨‍🍳 Head Chef: reads the order and decides the plan. Rule-based on purpose: free, instant, explainable."""
from ..domain.models import Plan


class HeadChef:
    def plan(self, question: str, pantry_has_docs: bool) -> Plan:
        q = question.lower()
        if not pantry_has_docs:
            return Plan("chat", 0)
        if any(w in q for w in ("compare", " vs ", "versus", "difference")):
            return Plan("compare", 8)
        if any(w in q for w in ("summar", "overview", "tl;dr", "main points")):
            return Plan("summary", 8)
        return Plan("lookup", 4)
