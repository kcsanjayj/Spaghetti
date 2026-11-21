"""The kitchen: five cooks in order, streaming events so the UI shows real progress and live tokens.

Fast by default: ONE model call (the Saucier, streamed). "Careful mode" adds an AI judge and one bounded retry.
"""
import time

from ..config import Settings
from ..domain.models import AskRequest
from ..runtimes.base import ModelError
from .head_chef import HeadChef
from .saucier import Saucier
from .sous_chef import SousChef
from .taster import Taster


class Kitchen:
    def __init__(self, pantry, engine, llm, model: str, settings: Settings, careful: bool = False):
        self.pantry, self.engine, self.settings, self.careful = pantry, engine, settings, careful
        self.head, self.sous = HeadChef(), SousChef(pantry)
        self.saucier, self.taster = Saucier(llm, model), Taster(llm, model, engine)

    def serve(self, req: AskRequest):
        t0, stages = time.perf_counter(), []

        def done(cook, detail, started):
            ms = round((time.perf_counter() - started) * 1000)
            stages.append({"cook": cook, "detail": detail, "ms": ms})
            return {"type": "stage", "cook": cook, "status": "done", "detail": detail, "ms": ms}

        try:
            summary_prepared = False
            s = time.perf_counter()
            yield {"type": "stage", "cook": "head_chef", "status": "start"}
            plan = self.head.plan(req.question, bool(self.pantry.docs))
            yield done("head_chef", f"plan: {plan.mode}", s)

            hits = []
            if plan.mode != "chat":
                s = time.perf_counter()
                yield {"type": "stage", "cook": "sous_chef", "status": "start"}
                hits = self.sous.fetch(req.question, plan.k, plan.mode)
                yield done("sous_chef", f"{len(hits)} ingredients ({self.engine.name} engine)", s)

            attempts, feedback, chunks, cook_s = [], "", 0, 0.0
            for attempt in range(1 + (self.settings.max_retries if self.careful else 0)):
                if attempt:
                    yield {"type": "reset"}  # the UI clears the streamed text before the second try
                    if plan.mode != "summary":
                        s = time.perf_counter()
                        yield {"type": "stage", "cook": "sous_chef", "status": "start"}
                        wider_k = min(plan.k * (2 ** attempt), 32)
                        hits = self.sous.refine(req.question, hits, wider_k, plan.mode)
                        yield done("sous_chef", f"refined evidence: {len(hits)} excerpts", s)
                s = time.perf_counter()
                yield {"type": "stage", "cook": "saucier", "status": "start"}
                if plan.mode == "summary" and not summary_prepared and hits:
                    summary = self.saucier.prepare_summary(hits)
                    while True:
                        try:
                            yield next(summary)
                        except StopIteration as stop:
                            hits = stop.value
                            summary_prepared = True
                            break
                answer_started = time.perf_counter()
                gen = self.saucier.cook_stream(req.question, hits, req.history, feedback,
                                               chat=plan.mode == "chat", summary=plan.mode == "summary")
                while True:
                    try:
                        ev = next(gen)
                    except StopIteration as stop:
                        answer, thoughts = stop.value
                        break
                    chunks += 1
                    yield ev
                cook_s += time.perf_counter() - answer_started
                yield done("saucier", f"attempt {attempt + 1}", s)
                if plan.mode == "chat" or not hits:
                    attempts.append((answer, None, thoughts))
                    break
                s = time.perf_counter()
                yield {"type": "stage", "cook": "taster", "status": "start"}
                verdict = self.taster.taste(req.question, answer, hits, self.careful)
                yield done("taster", f"{verdict.score}/10 ({verdict.method})", s)
                attempts.append((answer, verdict, thoughts))
                if verdict.score >= self.settings.pass_score:
                    break
                feedback = verdict.issues or "Stay closer to the excerpts."

            s = time.perf_counter()
            yield {"type": "stage", "cook": "expediter", "status": "start"}
            _, (answer, verdict, thoughts) = max(
                enumerate(attempts),
                key=lambda item: (item[1][1].score if item[1][1] else 0, item[0]),
            )
            yield done("expediter", "plated" if len(attempts) == 1 else f"best of {len(attempts)} attempts", s)
            yield {"type": "final", "answer": answer, "thoughts": thoughts, "mode": plan.mode, "attempts": len(attempts), "careful": self.careful,
                   "score": verdict.score if verdict else None, "grounded": round(verdict.grounded, 2) if verdict else None,
                   "tok_s": round(chunks / cook_s, 1) if chunks > 3 and cook_s else None,
                   "sources": [{"n": i, "doc": h.doc_name, "ids": list(h.source_ids or (h.doc_id,)),
                               "score": round(h.score, 2), "preview": h.text[:220]} for i, h in enumerate(hits, 1)],
                   "stages": stages, "total_ms": round((time.perf_counter() - t0) * 1000)}
        except ModelError as err:
            yield {"type": "error", "message": str(err), "code": err.code}
