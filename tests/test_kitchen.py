import io
import tempfile
import unittest
from pathlib import Path

from tests import helpers  # noqa: F401
from spaghetti.config import Settings
from spaghetti.domain.models import AskRequest
from spaghetti.engine.python_engine import PythonEngine
from spaghetti.kitchen import Kitchen
from spaghetti.pantry import Pantry
from spaghetti.pantry.store import extract_text
from spaghetti.runtimes.base import ModelError
from spaghetti.runtimes.mock import MockModel


class Scripted:
    """A fake provider that returns canned replies, so we can test retry logic without a network."""

    def __init__(self, *replies):
        self.replies, self.calls, self.messages, self.calls_messages = list(replies), 0, None, []

    def chat(self, messages, model):
        self.calls += 1
        self.messages = messages
        self.calls_messages.append(messages)
        return self.replies.pop(0)


def make(provider, text="Boil pasta in salted water for eight minutes. Drain well.", careful=False):
    pantry = Pantry(PythonEngine())
    if text:
        pantry.add("pasta.txt", text)
    return Kitchen(pantry, PythonEngine(), provider, "m", Settings(), careful)


def run(kitchen, q):
    return list(kitchen.serve(AskRequest(q)))


class KitchenTests(unittest.TestCase):
    def test_happy_path_cites_and_scores(self):
        final = run(make(MockModel(), careful=True), "How long to boil pasta?")[-1]
        self.assertEqual(final["type"], "final")
        self.assertEqual(final["attempts"], 1)
        self.assertGreaterEqual(final["score"], 7)
        self.assertEqual(final["sources"][0]["doc"], "pasta.txt")

    def test_summary_retrieves_documents_without_keyword_matches(self):
        provider = Scripted("Pasta section notes.", "The document explains pasta preparation.")
        events = run(make(provider), "summarize")
        final = events[-1]
        self.assertEqual(final["mode"], "summary")
        self.assertTrue(final["sources"][0]["doc"].startswith("pasta.txt"))
        sous = next(e for e in events if e.get("cook") == "sous_chef" and e.get("status") == "done")
        self.assertIn("1 ", sous["detail"])
        self.assertIn("whole-document summary", provider.messages[0]["content"])
        self.assertIn("Pasta section notes.", provider.messages[-1]["content"])
        self.assertIn("Boil pasta in salted water", provider.calls_messages[0][-1]["content"])

    def test_long_summary_covers_late_chunks_through_hierarchical_reduction(self):
        engine = PythonEngine()
        pantry = Pantry(engine, chunk_words=1, chunk_overlap=0)
        document = pantry.add("manual.txt", " ".join(f"SECTION{index}" for index in range(205)))
        replies = [f"section notes {index}" for index in range(18)]
        replies += ["combined notes one", "combined notes two", "whole document summary"]
        provider = Scripted(*replies)
        kitchen = Kitchen(pantry, engine, provider, "m", Settings())

        events = run(kitchen, "summarize")
        final = events[-1]

        self.assertEqual(final["answer"], "whole document summary")
        self.assertEqual(len(final["sources"]), 2)
        self.assertTrue(all(document.id in source["ids"] for source in final["sources"]))
        self.assertIn("[205] SECTION204", provider.calls_messages[17][-1]["content"])
        self.assertIn("combined notes one", provider.messages[-1]["content"])
        self.assertIn("combined notes two", provider.messages[-1]["content"])
        progress = [event for event in events if event["type"] == "progress"]
        self.assertEqual(len(progress), 20)
        self.assertEqual(progress[-1]["detail"], "Summarized 20 of 20 sections")

    def test_reduced_summary_sources_retain_all_document_ids(self):
        engine = PythonEngine()
        pantry = Pantry(engine)
        documents = [
            pantry.add(f"document-{index}.txt", f"Document {index} contains useful details.")
            for index in range(17)
        ]
        replies = [f"notes {index}" for index in range(17)] + ["combined one", "combined two", "final summary"]
        kitchen = Kitchen(pantry, engine, Scripted(*replies), "m", Settings())

        final = run(kitchen, "summarize")[-1]

        source_ids = {doc_id for source in final["sources"] for doc_id in source["ids"]}
        self.assertEqual(source_ids, {document.id for document in documents})

    def test_topic_summary_limits_chunks_to_matching_document(self):
        pantry = Pantry(PythonEngine())
        pantry.add("pasta.md", "Boil pasta in salted water for eight minutes.")
        pantry.add("pizza_dough.md", "Pizza dough uses flour, water, salt and yeast.")
        hits = pantry.summary_chunks("Summarize the pizza dough advice", 8)
        self.assertEqual({hit.doc_name for hit in hits}, {"pizza_dough.md"})

    def test_summary_of_named_file_includes_every_chunk(self):
        pantry = Pantry(PythonEngine(), chunk_words=1, chunk_overlap=0)
        pantry.add("The_AI_Engineer_Playbook.pdf", " ".join(f"SECTION{index}" for index in range(10)))
        hits = pantry.summary_chunks("Summarize the Playbook", 8)
        self.assertEqual(len(hits), 10)
        self.assertTrue(all(hit.doc_name == "The_AI_Engineer_Playbook.pdf" for hit in hits))

    def test_short_topic_prompt_uses_matching_excerpts(self):
        provider = Scripted("Python is used for data science and model deployment.")
        kitchen = make(provider, text="Python supports data science and production model deployment.")
        final = run(kitchen, "python")[-1]
        self.assertEqual(final["sources"][0]["doc"], "pasta.txt")
        self.assertIn("short topic or keyword", provider.messages[0]["content"])

    def test_weak_answer_triggers_exactly_one_retry(self):
        bad = Scripted("Pasta is Italian.", '{"score": 3, "issues": "off topic"}', "Boil pasta eight minutes.", '{"score": 9, "issues": ""}')
        final = run(make(bad, careful=True), "How long to boil pasta?")[-1]
        self.assertEqual(final["attempts"], 2)
        self.assertEqual(final["answer"], "Boil pasta eight minutes.")

    def test_retry_is_bounded(self):
        always_bad = Scripted(*(["x", '{"score": 1, "issues": "bad"}'] * 5))
        final = run(make(always_bad, careful=True), "How long to boil pasta?")[-1]
        self.assertEqual(final["attempts"], 2)  # 1 try + max_retries(1), never more
        self.assertEqual(always_bad.calls, 4)

    def test_retry_draft_wins_when_judge_scores_tie(self):
        provider = Scripted(
            "first draft", '{"score": 0, "issues": "answer the question"}',
            "revised draft", '{"score": 0, "issues": "still weak"}',
        )
        final = run(make(provider, careful=True), "How long to boil pasta?")[-1]
        self.assertEqual(final["answer"], "revised draft")

    def test_taster_retry_refines_retrieval_before_revising_answer(self):
        engine = PythonEngine()
        pantry = Pantry(engine, chunk_words=2, chunk_overlap=0)
        pantry.add("guide.txt", "python section1 python section2 python section3 python section4 python section5")
        provider = Scripted(
            "first draft", '{"score": 0, "issues": "missing the final section"}',
            "Python also covers section5 [5].", '{"score": 9, "issues": ""}',
        )
        kitchen = Kitchen(pantry, engine, provider, "m", Settings(), careful=True)

        events = run(kitchen, "python")
        final = events[-1]

        self.assertEqual(final["answer"], "Python also covers section5 [5].")
        self.assertEqual(len(final["sources"]), 5)
        self.assertIn("section5", provider.calls_messages[2][-1]["content"])
        self.assertTrue(any("refined evidence: 5 excerpts" in event.get("detail", "") for event in events))

    def test_broken_judge_falls_back_to_overlap(self):
        p = Scripted("Boil pasta in salted water.", "not json at all")
        final = run(make(p, careful=True), "How long to boil pasta?")[-1]
        self.assertIn("overlap", [s["detail"] for s in final["stages"] if s["cook"] == "taster"][0])

    def test_fast_mode_makes_exactly_one_model_call_and_never_retries(self):
        p = Scripted("Pasta is Italian.")  # a weak answer: fast mode still serves it, with one call
        final = run(make(p), "How long to boil pasta?")[-1]
        self.assertEqual((p.calls, final["attempts"], final["careful"]), (1, 1, False))

    def test_tokens_are_streamed_before_the_final_event(self):
        events = run(make(MockModel()), "How long to boil pasta?")
        kinds = [e["type"] for e in events]
        self.assertIn("token", kinds)
        self.assertLess(kinds.index("token"), kinds.index("final"))

    def test_retry_emits_reset_so_the_ui_can_clear_streamed_text(self):
        bad = Scripted("x", '{"score": 2, "issues": "bad"}', "Boil pasta eight minutes.", '{"score": 9, "issues": ""}')
        self.assertIn("reset", [e["type"] for e in run(make(bad, careful=True), "How long to boil pasta?")])

    def test_empty_pantry_is_plain_chat(self):
        events = run(make(Scripted("Hello!"), text=""), "hi")
        self.assertEqual(events[-1]["mode"], "chat")
        self.assertNotIn("sous_chef", [e.get("cook") for e in events])

    def test_no_ingredients_means_no_pointless_retry(self):
        p = Scripted("I could not find that in the pantry.")
        final = run(make(p), "zebra quantum?")[-1]
        self.assertEqual((final["attempts"], p.calls, final["score"]), (1, 1, None))

    def test_model_error_becomes_event_not_crash(self):
        class Boom:
            def chat(self, *_):
                raise ModelError("ollama stopped", "ollama_down")
        self.assertEqual(run(make(Boom()), "boil pasta?")[-1], {"type": "error", "message": "ollama stopped", "code": "ollama_down"})


class PantryTests(unittest.TestCase):
    def test_extracts_docx_text(self):
        from docx import Document
        document = Document()
        document.add_paragraph("Drain the spaghetti.")
        document.add_table(rows=1, cols=1)
        document.tables[0].cell(0, 0).text = "Save pasta water."
        output = io.BytesIO()
        document.save(output)
        text = extract_text("recipe.docx", output.getvalue())
        self.assertIn("Drain the spaghetti.", text)
        self.assertIn("Save pasta water.", text)

    def test_extracts_pdf_text(self):
        from reportlab.pdfgen import canvas
        output = io.BytesIO()
        document = canvas.Canvas(output)
        document.drawString(72, 72, "Boil pasta for eight minutes.")
        document.save()
        text = extract_text("recipe.pdf", output.getvalue())
        self.assertIn("Boil pasta for eight minutes.", text)

    def test_stray_word_match_is_filtered(self):
        pantry = Pantry(PythonEngine())
        pantry.add("a.txt", "Save one cup of pasta water before draining.")
        self.assertEqual(pantry.search("Who won the 2010 football world cup?", 4), [])
        self.assertEqual(len(pantry.search("why save pasta water?", 4)), 1)

    def test_prefix_match_finds_burns_for_burnt(self):
        pantry = Pantry(PythonEngine())
        pantry.add("a.txt", "Burnt garlic turns bitter.")
        self.assertEqual(len(pantry.search("What happens if garlic burns?", 4)), 1)

    def test_persists_and_reloads(self):
        path = Path(tempfile.mkdtemp()) / "p.json"
        Pantry(PythonEngine(), path).add("a.txt", "garlic oil")
        self.assertEqual(len(Pantry(PythonEngine(), path).docs), 1)

    def test_removal_persists_and_reloads_without_deleted_text(self):
        path = Path(tempfile.mkdtemp()) / "p.json"
        pantry = Pantry(PythonEngine(), path)
        doc = pantry.add("private.txt", "sensitive pantry contents")

        self.assertTrue(pantry.remove(doc.id))

        self.assertEqual(pantry.docs, {})
        self.assertEqual(Pantry(PythonEngine(), path).docs, {})
        self.assertNotIn("sensitive pantry contents", path.read_text(encoding="utf-8"))

    def test_failed_removal_save_keeps_document_in_memory(self):
        from unittest.mock import patch

        path = Path(tempfile.mkdtemp()) / "p.json"
        pantry = Pantry(PythonEngine(), path)
        doc = pantry.add("private.txt", "sensitive pantry contents")
        with patch.object(Path, "replace", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                pantry.remove(doc.id)

        self.assertIn(doc.id, pantry.docs)
        self.assertIn("sensitive pantry contents", path.read_text(encoding="utf-8"))

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            Pantry(PythonEngine()).add("a.txt", "   ")


if __name__ == "__main__":
    unittest.main()
