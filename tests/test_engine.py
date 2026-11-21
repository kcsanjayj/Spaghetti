import unittest

from tests import helpers  # noqa: F401
from spaghetti.engine.loader import find_binary
from spaghetti.engine.python_engine import PythonEngine
from spaghetti.engine.rust_engine import RustEngine

TEXT = " ".join(f"word{i} pasta{i % 3} sauce" for i in range(60))
DOCS = ["boil pasta eight minutes salted water", "bake bread flour yeast", "pasta sauce garlic oil tomato"]


class PythonEngineTests(unittest.TestCase):
    def test_chunk_overlap(self):
        self.assertEqual(PythonEngine().chunk("a1 b2 c3 d4 e5 f6", 4, 2), ["a1 b2 c3 d4", "c3 d4 e5 f6"])

    def test_rank_orders_by_relevance(self):
        ranked = PythonEngine().rank("boil pasta", DOCS, 3)
        self.assertEqual(ranked[0][0], 0)
        self.assertNotIn(1, [i for i, _ in ranked])  # unrelated doc never appears

    def test_overlap(self):
        self.assertAlmostEqual(PythonEngine().overlap("pasta sauce", "pasta water"), 0.5)


@unittest.skipUnless(find_binary(), "Rust core not built (run: python run.py build)")
class RustParityTests(unittest.TestCase):
    """The Rust and Python engines must agree. This is what makes the fallback safe."""

    def setUp(self):
        self.py, self.rs = PythonEngine(), RustEngine(find_binary())

    def test_chunk_parity(self):
        self.assertEqual(self.py.chunk(TEXT, 17, 5), self.rs.chunk(TEXT, 17, 5))

    def test_rank_parity(self):
        a, b = self.py.rank("pasta sauce garlic", DOCS, 3), self.rs.rank("pasta sauce garlic", DOCS, 3)
        self.assertEqual([i for i, _ in a], [i for i, _ in b])
        for (_, x), (_, y) in zip(a, b):
            self.assertAlmostEqual(x, y, places=5)

    def test_overlap_parity(self):
        self.assertAlmostEqual(self.py.overlap("garlic pasta soup", DOCS[2]), self.rs.overlap("garlic pasta soup", DOCS[2]), places=5)


if __name__ == "__main__":
    unittest.main()
