import json
import tempfile
import unittest
from pathlib import Path

from tests import helpers  # noqa: F401
from eval import harness as H
from eval import metrics as M
from spaghetti.config import Settings
from spaghetti.engine.python_engine import PythonEngine


class MetricTests(unittest.TestCase):
    def test_keyword_recall_supports_alternatives_and_punctuation(self):
        self.assertEqual(M.keyword_recall("Cook it for 10 minutes.", ["ten|10", "minutes"]), 1.0)
        self.assertEqual(M.keyword_recall("About eight.", ["eight", "minutes"]), 0.5)
        self.assertEqual(M.keyword_recall("anything", []), 1.0)

    def test_abstention_detection(self):
        self.assertTrue(M.abstained("I could not find that in the pantry.", []))
        self.assertFalse(M.abstained("Boil it for ten minutes.", []))

    def test_retrieval_scores(self):
        self.assertEqual(M.retrieval_scores(["b", "a"], ["a"]), {"hit": 1.0, "doc_recall": 1.0, "rr": 0.5})
        self.assertEqual(M.retrieval_scores(["b"], ["a", "b"])["doc_recall"], 0.5)
        self.assertEqual(M.retrieval_scores([], ["a"])["rr"], 0.0)

    def test_citation_accuracy(self):
        src = [{"n": 1, "doc": "a.md"}, {"n": 2, "doc": "b.md"}]
        self.assertEqual(M.citation_accuracy("Yes [1].", src, ["a.md"]), 1.0)
        self.assertEqual(M.citation_accuracy("Yes [2].", src, ["a.md"]), 0.0)   # cites the wrong document
        self.assertEqual(M.citation_accuracy("Yes.", src, ["a.md"]), 0.0)        # no citation at all
        self.assertEqual(M.citation_accuracy("Yes [9].", src, ["a.md"]), 0.0)    # invented source number

    def test_injection_and_percentiles(self):
        self.assertTrue(M.injected("PWNED!", ["pwned"]))
        self.assertFalse(M.injected("garlic and wine", ["pwned"]))
        self.assertEqual(M.percentile([1, 2, 3, 4, 100], 0.5), 3)


class DatasetTests(unittest.TestCase):
    def test_shipped_dataset_is_valid_and_covers_every_question_type(self):
        data = H.load_dataset()
        types = {q["type"] for q in data["questions"]}
        self.assertTrue({"lookup", "numeric", "multi", "summary", "unanswerable", "injection", "synonym"} <= types)
        self.assertTrue(any(q.get("known_limitation") for q in data["questions"]))

    def test_invalid_datasets_are_rejected(self):
        bad = {"name": "x", "docs": {"a.md": "text"}, "questions": [{"id": "q", "type": "lookup", "q": "?", "expect_docs": ["missing.md"]}]}
        path = Path(tempfile.mkdtemp()) / "bad.json"
        path.write_text(json.dumps(bad))
        with self.assertRaises(ValueError):
            H.load_dataset(path)

    def test_tag_and_type_selection(self):
        data = H.load_dataset()
        self.assertTrue(all(q["type"] == "numeric" for q in H.select(data, ["numeric"])))
        self.assertEqual(len(H.select(data, None, None, 3)), 3)


class GateTests(unittest.TestCase):
    def test_min_and_max_thresholds(self):
        t = {"min": {"hit_at_k": 0.9}, "max": {"error_rate": 0.0}}
        self.assertEqual(H.gate({"hit_at_k": 0.95, "error_rate": 0.0}, t), [])
        self.assertEqual(len(H.gate({"hit_at_k": 0.5, "error_rate": 0.2}, t)), 2)
        self.assertEqual(H.gate({"hit_at_k": None}, t), [])  # not applicable is not a failure

    def test_baseline_diff_flags_regressions_only(self):
        self.assertEqual(H.diff_against({"hit_at_k": 0.97}, {"hit_at_k": 1.0}), [])          # within tolerance
        self.assertEqual(len(H.diff_against({"hit_at_k": 0.8}, {"hit_at_k": 1.0})), 1)
        self.assertEqual(len(H.diff_against({"p95_ms": 900}, {"p95_ms": 100})), 1)


class ScriptedModel:
    def __init__(self, reply):
        self.reply = reply

    def chat(self, messages, model):
        return self.reply


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.data, self.engine, self.settings = H.load_dataset(), PythonEngine(), Settings()

    def run_with(self, reply, ids=None, careful=False):
        qs = [q for q in self.data["questions"] if not ids or q["id"] in ids]
        return H.run_config(H.Config("t", careful), self.data, self.engine, self.settings, ScriptedModel(reply), "m", qs)

    def test_a_model_that_obeys_the_injected_instruction_is_caught(self):
        run = self.run_with("PWNED", ["injection-01"])
        self.assertEqual(run["summary"]["injection_resistance"], 0.0)
        self.assertTrue(H.gate(run["summary"], {"min": {"injection_resistance": 1.0}}))

    def test_a_model_that_always_abstains_fails_answerable_questions(self):
        run = self.run_with("I could not find that in the pantry.", ["lookup-01", "unanswerable-01"])
        self.assertEqual(run["summary"]["abstention"], 1.0)
        self.assertEqual(run["summary"]["keyword_recall"], 0.0)

    def test_known_limitations_are_reported_but_excluded_from_the_gated_summary(self):
        run = self.run_with("x", ["lookup-01", "synonym-01"])
        self.assertEqual(run["summary"]["cases"], 1)
        self.assertEqual(run["known_limitations"]["cases"], 1)

    def test_provider_errors_count_as_errors_not_crashes(self):
        class Boom:
            def chat(self, *_):
                from spaghetti.runtimes.base import ModelError
                raise ModelError("down", "ollama_down")
        run = H.run_config(H.Config("t", False), self.data, self.engine, self.settings, Boom(), "m", H.select(self.data, None, None, 2))
        self.assertEqual(run["summary"]["error_rate"], 1.0)

    def test_coverage_filter_improves_abstention_without_hurting_retrieval(self):
        qs = self.data["questions"]
        off = H.retrieval_run(self.engine, self.data, self.settings, qs, 4, 0.0)["summary"]
        on = H.retrieval_run(self.engine, self.data, self.settings, qs, 4, 0.4)["summary"]
        self.assertGreater(on["abstention"], off["abstention"])
        self.assertGreaterEqual(on["hit_at_k"], off["hit_at_k"])


class EndToEndTests(unittest.TestCase):
    def test_default_mock_run_passes_its_gate_and_writes_reports(self):
        out = tempfile.mkdtemp()
        self.assertEqual(H.main(["--configs", "fast,careful", "--out", out]), 0)
        report = json.loads((Path(out) / "report.json").read_text())
        self.assertEqual([r["config"] for r in report["runs"]], ["fast", "careful"])
        self.assertTrue((Path(out) / "report.md").read_text().startswith("# Spaghetti evaluation"))

    def test_retrieval_only_mode_runs_without_a_model(self):
        self.assertEqual(H.main(["--retrieval-only", "--out", tempfile.mkdtemp()]), 0)

    def test_regression_against_a_better_baseline_fails_the_run(self):
        base = Path(tempfile.mkdtemp()) / "b.json"
        base.write_text(json.dumps({"fast": {"keyword_recall": 5.0}}))  # impossible-to-match baseline
        self.assertEqual(H.main(["--configs", "fast", "--baseline", str(base), "--out", tempfile.mkdtemp()]), 1)
        self.assertEqual(H.main(["--configs", "fast", "--baseline", str(base), "--no-gate", "--out", tempfile.mkdtemp()]), 0)

    def test_shipped_baseline_is_current(self):
        self.assertEqual(H.main(["--baseline", str(H.ROOT / "eval" / "baseline.mock.json"), "--out", tempfile.mkdtemp()]), 0)


if __name__ == "__main__":
    unittest.main()
