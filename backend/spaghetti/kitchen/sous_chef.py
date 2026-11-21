"""🧑‍🍳 Sous Chef: fetches the right ingredients (BM25 ranking through the Rust engine)."""


class SousChef:
    def __init__(self, pantry):
        self.pantry = pantry

    def fetch(self, question: str, k: int, mode: str = "lookup"):
        if mode == "summary":
            return self.pantry.summary_chunks(question, k)
        return self.pantry.search(question, k)

    def refine(self, question: str, current, k: int, mode: str = "lookup"):
        expanded = self.fetch(question, k, mode)
        seen = {(hit.doc_id, hit.text) for hit in current}
        return current + [hit for hit in expanded if (hit.doc_id, hit.text) not in seen]
