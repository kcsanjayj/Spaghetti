"""Bridge to the Rust binary: plain text over stdin/stdout, no FFI."""
import subprocess

RS = "\x1e"


class RustEngine:
    name = "rust"

    def __init__(self, binary: str):
        self.binary = binary

    def _run(self, *args: str, stdin: str) -> str:
        done = subprocess.run(
            [self.binary, *args], input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=20
        )
        if done.returncode != 0:
            raise RuntimeError(done.stderr.strip() or "spaghetti-core failed")
        return done.stdout

    def chunk(self, text, size=120, overlap=20):
        out = self._run("chunk", str(size), str(overlap), stdin=text)
        return out.split(RS) if out else []

    def rank(self, query, chunks, k=4):
        if not chunks:
            return []
        out = self._run("rank", str(k), stdin=query.replace("\n", " ") + "\n" + RS.join(chunks))
        pairs = (line.split("\t") for line in out.splitlines() if line)
        return [(int(i), float(s)) for i, s in pairs]

    def overlap(self, answer, context):
        return float(self._run("overlap", stdin=answer + RS + context))

    def hardware(self):
        rows = (line.partition("=") for line in self._run("hw", stdin="").splitlines() if "=" in line)
        return {k: (int(v) if v.isdigit() else v) for k, _, v in rows}
