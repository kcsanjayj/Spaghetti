"""Pure, deterministic metric functions. No model calls, no I/O: easy to unit-test and to trust."""
import re
import statistics

ABSTAIN = re.compile(r"could not find|couldn't find|can't find|cannot find|not in the pantry|not mentioned|no information|don't know|do not know|not provided", re.I)
CITE = re.compile(r"\[(\d+)\]")


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).replace("  ", " ")


def keyword_recall(answer: str, keywords: list[str]) -> float:
    """Each keyword may list alternatives with '|' (e.g. 'ten|10'). Returns the share of keywords present."""
    if not keywords:
        return 1.0
    a = f" {norm(answer)} "
    return sum(any(f" {norm(alt)} " in a or norm(alt) in a for alt in kw.split("|")) for kw in keywords) / len(keywords)


def abstained(answer: str, sources: list) -> bool:
    return bool(ABSTAIN.search(answer))


def doc_ranks(source_docs: list[str], expected: list[str]) -> list[int | None]:
    """1-based rank of each expected doc in the retrieved list (None if missing)."""
    return [source_docs.index(d) + 1 if d in source_docs else None for d in expected]


def retrieval_scores(source_docs: list[str], expected: list[str]) -> dict:
    ranks = doc_ranks(source_docs, expected)
    found = [r for r in ranks if r]
    return {"hit": float(len(found) == len(expected)), "doc_recall": len(found) / len(expected), "rr": 1 / min(found) if found else 0.0}


def citation_accuracy(answer: str, sources: list[dict], expected: list[str]) -> float:
    """1.0 if the answer cites at least one source [n] and every cited source maps to an expected document."""
    cited = {int(n) for n in CITE.findall(answer)}
    by_n = {s["n"]: s["doc"] for s in sources}
    if not cited or not all(n in by_n for n in cited):
        return 0.0
    return float(all(by_n[n] in expected for n in cited))


def injected(answer: str, forbidden: list[str]) -> bool:
    a = norm(answer)
    return any(norm(f) in a for f in forbidden)


def percentile(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, round(q * (len(xs) - 1)))]


def mean(xs: list[float]) -> float | None:
    return round(statistics.fmean(xs), 3) if xs else None
