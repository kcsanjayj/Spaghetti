"""Spaghetti evaluation harness.

  python run.py eval                          offline mock model, full pipeline, gated by thresholds.json
  python run.py eval --retrieval-only         no model at all: retrieval quality + ablations (meaningful in CI)
  python run.py eval --model qwen3:1.7b       a real Ollama model (answer metrics are reported, retrieval gated)
  python run.py eval --configs fast,careful   compare pipeline modes on the same questions
  python run.py eval --tag numeric --limit 5  slice the dataset
  python run.py eval --baseline eval/baseline.mock.json     fail on regressions vs a saved run
  python run.py eval --save-baseline eval/baseline.mock.json

Exit code 1 = a threshold or baseline gate failed (use it in CI).
Cases marked `known_limitation` are reported but never gate the build: they document what the system cannot do.
"""
import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from eval import metrics as M  # noqa: E402
from spaghetti.config import Settings  # noqa: E402
from spaghetti.domain.models import AskRequest  # noqa: E402
from spaghetti.engine import load_engine  # noqa: E402
from spaghetti.kitchen import Kitchen  # noqa: E402
from spaghetti.kitchen.head_chef import HeadChef  # noqa: E402
from spaghetti.pantry import Pantry  # noqa: E402
from spaghetti.runtimes.registry import build_model  # noqa: E402

DATASET = ROOT / "eval" / "datasets" / "kitchen.json"
THRESHOLDS = ROOT / "eval" / "thresholds.json"
REGRESSION_TOLERANCE = 0.05


@dataclass(frozen=True)
class Config:
    name: str
    careful: bool


CONFIGS = {"fast": Config("fast", False), "careful": Config("careful", True)}


# ---------- data ----------
def load_dataset(path: Path = DATASET) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    ids = [q["id"] for q in data["questions"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate question ids")
    for q in data["questions"]:
        missing = [d for d in q.get("expect_docs", []) if d not in data["docs"]]
        if missing:
            raise ValueError(f"{q['id']}: unknown expected docs {missing}")
        if not q.get("should_abstain") and not q.get("expect_docs"):
            raise ValueError(f"{q['id']}: answerable questions need expect_docs")
    return data


def select(data: dict, tags=None, types=None, limit=None) -> list[dict]:
    qs = [q for q in data["questions"] if (not tags or set(tags) & set(q.get("tags", []) + [q["type"]])) and (not types or q["type"] in types)]
    return qs[:limit] if limit else qs


def build_pantry(engine, data, settings: Settings) -> Pantry:
    pantry = Pantry(engine, None, settings.chunk_words, settings.chunk_overlap)
    for name, text in data["docs"].items():
        pantry.add(name, text)
    return pantry


# ---------- one case ----------
def grade(case: dict, final: dict) -> dict:
    """Turn a final event into per-case metric values. None = metric not applicable to this case."""
    answer, sources = final["answer"], final["sources"]
    docs = [s["doc"] for s in sources]
    r = {"id": case["id"], "type": case["type"], "known_limitation": bool(case.get("known_limitation")), "answer": answer, "sources": docs,
         "ms": final["total_ms"], "tok_s": final.get("tok_s"), "attempts": final["attempts"], "error": None,
         "hit_at_k": None, "mrr": None, "doc_recall": None, "keyword_recall": None, "groundedness": None, "citation_accuracy": None, "abstention": None, "injection_resistance": None}
    if case.get("should_abstain"):
        r["abstention"] = float(M.abstained(answer, sources))
    else:
        rs = M.retrieval_scores(docs, case["expect_docs"])
        r.update(hit_at_k=rs["hit"], mrr=rs["rr"], doc_recall=rs["doc_recall"], keyword_recall=M.keyword_recall(answer, case.get("keywords", [])),
                 groundedness=final.get("grounded"), citation_accuracy=M.citation_accuracy(answer, sources, case["expect_docs"]))
    if case.get("forbidden"):
        r["injection_resistance"] = float(not M.injected(answer, case["forbidden"]))
    return r


def run_case(kitchen: Kitchen, case: dict) -> dict:
    final = None
    for ev in kitchen.serve(AskRequest(case["q"])):
        if ev["type"] in ("final", "error"):
            final = ev
    if not final or final["type"] == "error":
        return {"id": case["id"], "type": case["type"], "known_limitation": bool(case.get("known_limitation")), "error": (final or {}).get("message", "no result"),
                "ms": 0, "answer": "", "sources": []}
    return grade(case, final)


# ---------- aggregation ----------
KEYS = ["hit_at_k", "mrr", "doc_recall", "keyword_recall", "groundedness", "citation_accuracy", "abstention", "injection_resistance"]


def summarize(cases: list[dict]) -> dict:
    ok = [c for c in cases if not c.get("error")]
    s = {k: M.mean([c[k] for c in ok if c.get(k) is not None]) for k in KEYS}
    ms = [c["ms"] for c in ok]
    s.update(cases=len(cases), error_rate=round(1 - len(ok) / len(cases), 3) if cases else 0.0, p50_ms=round(M.percentile(ms, .5)), p95_ms=round(M.percentile(ms, .95)),
             tok_s=M.mean([c["tok_s"] for c in ok if c.get("tok_s")]), retry_rate=M.mean([float(c["attempts"] > 1) for c in ok]))
    return s


def by_type(cases: list[dict]) -> dict:
    return {t: summarize([c for c in cases if c["type"] == t]) for t in sorted({c["type"] for c in cases})}


def run_config(cfg: Config, data, engine, settings, llm, model, questions) -> dict:
    pantry = build_pantry(engine, data, settings)
    kitchen = Kitchen(pantry, engine, llm, model, settings, cfg.careful)
    cases = [run_case(kitchen, q) for q in questions]
    gated = [c for c in cases if not c["known_limitation"]]
    return {"config": cfg.name, "careful": cfg.careful, "cases": cases, "summary": summarize(gated), "known_limitations": summarize([c for c in cases if c["known_limitation"]]) if len(gated) != len(cases) else None, "by_type": by_type(cases)}


# ---------- retrieval-only (no model) ----------
def retrieval_run(engine, data, settings, questions, k_override=None, min_cov=None) -> dict:
    pantry, head, cases = build_pantry(engine, data, settings), HeadChef(), []
    for q in questions:
        k = k_override or head.plan(q["q"], True).k
        t0 = time.perf_counter()
        hits = pantry.search(q["q"], k) if min_cov is None else pantry.search(q["q"], k, min_cov)
        docs = list(dict.fromkeys(h.doc_name for h in hits))
        c = {"id": q["id"], "type": q["type"], "known_limitation": bool(q.get("known_limitation")), "sources": docs, "ms": round((time.perf_counter() - t0) * 1000, 2), "answer": "", "attempts": 1, "error": None,
             **{key: None for key in KEYS}}
        if q.get("should_abstain"):
            c["abstention"] = float(not hits)
        else:
            rs = M.retrieval_scores(docs, q["expect_docs"])
            c.update(hit_at_k=rs["hit"], mrr=rs["rr"], doc_recall=rs["doc_recall"])
        cases.append(c)
    gated = [c for c in cases if not c["known_limitation"]]
    return {"config": "retrieval", "careful": None, "cases": cases, "summary": summarize(gated), "by_type": by_type(cases)}


def ablation(engine, data, settings, questions) -> list[dict]:
    rows = []
    for k in (2, 4, 8):
        for cov in (0.0, 0.2, 0.4, 0.6):
            s = retrieval_run(engine, data, settings, questions, k, cov)["summary"]
            rows.append({"k": k, "min_coverage": cov, "hit_at_k": s["hit_at_k"], "mrr": s["mrr"], "abstention": s["abstention"]})
    return rows


# ---------- gates ----------
def gate(summary: dict, thresholds: dict) -> list[str]:
    fails = []
    for key, floor in thresholds.get("min", {}).items():
        v = summary.get(key)
        if v is not None and v < floor:
            fails.append(f"{key} {v} < {floor}")
    for key, ceil in thresholds.get("max", {}).items():
        v = summary.get(key)
        if v is not None and v > ceil:
            fails.append(f"{key} {v} > {ceil}")
    return fails


def diff_against(current: dict, baseline: dict, tol: float = REGRESSION_TOLERANCE) -> list[str]:
    """Higher-is-better metrics may not drop by more than `tol`; latency may not grow by more than 50%."""
    out = []
    for key in KEYS:
        a, b = current.get(key), baseline.get(key)
        if a is not None and b is not None and a < b - tol:
            out.append(f"{key} regressed {b} -> {a}")
    if baseline.get("p95_ms") and current.get("p95_ms", 0) > baseline["p95_ms"] * 1.5 + 50:
        out.append(f"p95_ms regressed {baseline['p95_ms']} -> {current['p95_ms']}")
    return out


# ---------- reporting ----------
COLS = ["hit_at_k", "mrr", "keyword_recall", "groundedness", "citation_accuracy", "abstention", "injection_resistance", "error_rate", "p50_ms", "p95_ms", "tok_s"]
fmt = lambda v: "-" if v is None else str(v)  # noqa: E731


def to_markdown(report: dict) -> str:
    out = [f"# Spaghetti evaluation\n", f"Dataset **{report['dataset']}** ({report['questions']} cases) · model **{report['model']}** · engine **{report['engine']}** · {report['when']}\n",
           "| Config | " + " | ".join(COLS) + " |", "|---|" + "---|" * len(COLS)]
    for r in report["runs"]:
        out.append(f"| {r['config']} | " + " | ".join("-" if (c == "tok_s" and report["model"] == "mock") else fmt(r["summary"].get(c)) for c in COLS) + " |")
    run = report["runs"][-1]
    out += ["", f"## By question type ({run['config']})", "| Type | n | hit@k | mrr | keyword | abstention |", "|---|---|---|---|---|---|"]
    out += [f"| {t} | {s['cases']} | {fmt(s['hit_at_k'])} | {fmt(s['mrr'])} | {fmt(s['keyword_recall'])} | {fmt(s['abstention'])} |" for t, s in run["by_type"].items()]
    bad = [c for c in run["cases"] if not c["known_limitation"] and (c.get("error") or c.get("hit_at_k") == 0 or c.get("abstention") == 0 or c.get("injection_resistance") == 0)]
    out += ["", "## Failing cases", *(f"- `{c['id']}`: {c.get('error') or 'retrieval/abstention/injection failure'} → {c['answer'][:90]!r} sources={c['sources']}" for c in bad)] if bad else ["", "## Failing cases", "None."]
    kl = [c for c in run["cases"] if c["known_limitation"]]
    if kl:
        out += ["", "## Known limitations (reported, never gate the build)", *(f"- `{c['id']}`: hit={c.get('hit_at_k')} sources={c['sources']}" for c in kl)]
    if report.get("ablation"):
        out += ["", "## Retrieval ablation (k × minimum word coverage)", "| k | min coverage | hit@k | mrr | abstention |", "|---|---|---|---|---|"]
        out += [f"| {a['k']} | {a['min_coverage']} | {a['hit_at_k']} | {a['mrr']} | {a['abstention']} |" for a in report["ablation"]]
    out += ["", "## Gate", *(report["gate_failures"] or ["All thresholds passed."])]
    if report["model"] == "mock":
        out += ["", "> The offline mock is extractive: answer-quality metrics only prove the plumbing. Run with a real model (`--model <tag>`) for real quality."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="mock", help="Ollama tag (e.g. qwen3:1.7b) or 'mock' for the deterministic offline model")
    ap.add_argument("--configs", default="fast,careful", help="comma list of: fast, careful")
    ap.add_argument("--retrieval-only", action="store_true", help="skip the model entirely; evaluate retrieval and ablations")
    ap.add_argument("--tag", action="append", help="only cases with this tag or type (repeatable)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dataset", default=str(DATASET))
    ap.add_argument("--baseline", help="JSON from a previous run: fail if metrics regress")
    ap.add_argument("--save-baseline", help="write this run's summary as a baseline")
    ap.add_argument("--no-gate", action="store_true", help="report only; never fail")
    ap.add_argument("--out", default=str(ROOT / "eval" / "results"))
    args = ap.parse_args(argv)

    settings = Settings(demo=True)
    engine = load_engine(settings.engine)
    data = load_dataset(Path(args.dataset))
    questions = select(data, args.tag, None, args.limit)
    if not questions:
        print("No questions selected.")
        return 2
    kind = "retrieval" if args.retrieval_only else ("mock" if args.model == "mock" else "live")
    thresholds = json.loads(THRESHOLDS.read_text())[kind]

    if args.retrieval_only:
        runs = [retrieval_run(engine, data, settings, questions)]
    else:
        llm = build_model(settings, args.model)
        runs = [run_config(CONFIGS[n], data, engine, settings, llm, args.model, questions) for n in args.configs.split(",")]
    failures = [f"[{r['config']}] {f}" for r in runs for f in gate(r["summary"], thresholds)]
    if args.baseline:
        base = json.loads(Path(args.baseline).read_text())
        for r in runs:
            failures += [f"[{r['config']}] {f}" for f in diff_against(r["summary"], base.get(r["config"], {}))]
    report = {"dataset": data["name"], "questions": len(questions), "model": "retrieval-only" if args.retrieval_only else args.model, "engine": engine.name,
              "when": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "runs": runs, "gate_failures": failures,
              "ablation": ablation(engine, data, settings, questions) if args.retrieval_only else None}
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    (out / "report.md").write_text(to_markdown(report), encoding="utf-8")
    if args.save_baseline:
        Path(args.save_baseline).write_text(json.dumps({r["config"]: r["summary"] for r in runs}, indent=1), encoding="utf-8")
    print(to_markdown(report))
    print("RESULT:", "FAIL" if failures and not args.no_gate else "PASS")
    return 1 if failures and not args.no_gate else 0


if __name__ == "__main__":
    sys.exit(main())
