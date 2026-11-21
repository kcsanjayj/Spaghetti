"""🍳 Saucier: cooks the answer with the chosen model, using only the fetched ingredients."""
import math

from ..domain.models import Hit
from ..runtimes.base import ModelError
from .thinking import ThinkSplitter, split_thinking

CHAT = "You are Spaghetti, a friendly, concise kitchen assistant. Answer clearly in a few short paragraphs."
GROUNDED = (
    "You answer ONLY from the numbered pantry excerpts. Cite sources like [1]. "
    "For a short topic or keyword, explain what the excerpts say about it instead of repeating a title or heading. "
    "If the excerpts do not contain the answer, say you could not find it in the pantry. Be concise."
)
SUMMARY = (
    "This is a whole-document summary request. Synthesize all provided section summaries, preserving important "
    "details and differences. Do not require the request's wording to appear in an excerpt or claim the pantry is empty."
)
SECTION_BATCH_SIZE = 12
REDUCE_BATCH_SIZE = 16
MAX_FINAL_SUMMARY_NOTES = 16
SECTION_PROMPT = (
    "ROLE:SECTION_SUMMARY Summarize every important point in this document section using only its excerpts. "
    "Preserve names, numbers, steps, and caveats. Be concise (at most 100 words) and do not add outside facts."
)
REDUCE_PROMPT = (
    "ROLE:SUMMARY_REDUCE Combine every important point from these section summaries into a faithful, concise note (at most 180 words). "
    "Preserve document names, distinctions, numbers, and caveats. Do not add outside facts."
)


class Saucier:
    def __init__(self, llm, model: str):
        self.llm, self.model = llm, model

    def prepare_summary(self, hits):
        documents = {}
        for hit in hits:
            documents.setdefault(hit.doc_id, []).append(hit)
        batches = [
            (doc_hits[0].doc_name, start, doc_hits[start:start + SECTION_BATCH_SIZE])
            for doc_hits in documents.values()
            for start in range(0, len(doc_hits), SECTION_BATCH_SIZE)
        ]
        call_count = len(batches)
        reduced_count = call_count
        while reduced_count > MAX_FINAL_SUMMARY_NOTES:
            reduced_count = math.ceil(reduced_count / REDUCE_BATCH_SIZE)
            call_count += reduced_count

        completed = 0
        notes = []
        for name, start, batch in batches:
            end = start + len(batch)
            excerpts = "\n\n".join(f"[{start + i + 1}] {hit.text}" for i, hit in enumerate(batch))
            user = (
                f"DOCUMENT: {name}\nCHUNKS: {start + 1}-{end}\n{excerpts}\n\n"
                "QUESTION: Summarize all important content from these chunks."
            )
            text = self.llm.chat(
                [{"role": "system", "content": SECTION_PROMPT}, {"role": "user", "content": user}],
                self.model,
            ).strip()
            if not text:
                raise ModelError("The model returned an empty summary for a document section.")
            source_ids = tuple(dict.fromkeys(
                source_id for hit in batch for source_id in (hit.source_ids or (hit.doc_id,))
            ))
            notes.append(Hit(
                batch[0].doc_id, name,
                f"Source chunks {start + 1}-{end}: {' '.join(text.split())}", 0.0, source_ids,
            ))
            completed += 1
            yield {"type": "progress", "detail": f"Summarized {completed} of {call_count} sections"}

        level = 1
        while len(notes) > MAX_FINAL_SUMMARY_NOTES:
            reduced = []
            for start in range(0, len(notes), REDUCE_BATCH_SIZE):
                batch = notes[start:start + REDUCE_BATCH_SIZE]
                user = "\n\n".join(
                    f"[{start + i + 1}] {note.doc_name}: {note.text}"
                    for i, note in enumerate(batch)
                )
                text = self.llm.chat(
                    [{"role": "system", "content": REDUCE_PROMPT},
                     {"role": "user", "content": f"{user}\n\nQUESTION: Combine all section summaries."}],
                    self.model,
                ).strip()
                if not text:
                    raise ModelError("The model returned an empty combined summary.")
                names = list(dict.fromkeys(note.doc_name for note in batch))
                doc_id = batch[0].doc_id if len({note.doc_id for note in batch}) == 1 else f"summary-{level}-{len(reduced) + 1}"
                source_ids = tuple(dict.fromkeys(
                    source_id for note in batch for source_id in (note.source_ids or (note.doc_id,))
                ))
                provenance = "; ".join(dict.fromkeys(note.text.splitlines()[0] for note in batch))
                reduced.append(Hit(
                    doc_id, ", ".join(names),
                    f"Source sections: {provenance}\n{' '.join(text.split())}", 0.0, source_ids,
                ))
                completed += 1
                yield {"type": "progress", "detail": f"Summarized {completed} of {call_count} sections"}
            notes, level = reduced, level + 1
        return notes

    def _messages(self, question, hits, history, feedback, chat, summary):
        past = [m for m in history if m.get("role") in ("user", "assistant")][-6:]
        if chat:  # empty pantry: plain assistant, no citations
            return [{"role": "system", "content": CHAT}, *past, {"role": "user", "content": question}]
        pantry = "\n".join(f"[{i}] {h.text}" for i, h in enumerate(hits, 1)) or "(nothing relevant found)"
        instruction = f"{GROUNDED} {SUMMARY}" if summary else GROUNDED
        note = (
            f"\nA taster said your last attempt was weak: {feedback}\n"
            "Revise the answer to address the question using the excerpts; do not repeat the previous draft."
        ) if feedback else ""
        return [{"role": "system", "content": instruction}, *past, {"role": "user", "content": f"PANTRY:\n{pantry}{note}\n\nQUESTION: {question}"}]

    def cook_stream(self, question, hits, history, feedback: str = "", chat: bool = False, summary: bool = False):
        """Generator: yields {"type":"token","kind":"answer"|"think","text"} while the model writes; returns (answer, thoughts)."""
        messages, raw = self._messages(question, hits, history, feedback, chat, summary), ""
        stream = getattr(self.llm, "chat_stream", None)
        if stream:
            splitter = ThinkSplitter()
            for chunk in stream(messages, self.model):
                raw += chunk
                for kind, text in splitter.feed(chunk):
                    yield {"type": "token", "kind": kind, "text": text}
            for kind, text in splitter.flush():
                yield {"type": "token", "kind": kind, "text": text}
        else:  # a model without streaming: one piece
            raw = self.llm.chat(messages, self.model)
            answer, thoughts = split_thinking(raw)
            if thoughts:
                yield {"type": "token", "kind": "think", "text": thoughts}
            yield {"type": "token", "kind": "answer", "text": answer}
        answer, thoughts = split_thinking(raw)
        return answer or "(The model used all its room thinking. Try a larger model.)", thoughts
