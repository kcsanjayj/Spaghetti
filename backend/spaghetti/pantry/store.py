"""The pantry = your documents. Plain JSON on disk, chunks rebuilt on load."""
import io
import json
import re
import zipfile
import uuid
from pathlib import Path

from ..domain.models import Document, Hit
from ..engine.python_engine import tokenize

ALLOWED = (".txt", ".md", ".csv", ".json", ".log", ".py", ".js", ".html", ".css", ".rs", ".toml", ".yaml", ".yml", ".pdf", ".docx")
MAX_CHARS = 400_000
MIN_COVERAGE = 0.4  # a hit must contain at least 40% of the question's key words
SUMMARY_WORDS = set(tokenize("summarize summary overview main points key document documents file files all everything your our"))


def extract_text(name: str, data: bytes) -> str:
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED:
        raise ValueError("Unsupported file type. Use PDF, DOCX, or a text document.")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            text = "\n\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
        except Exception as err:
            try:
                import pymupdf
                with pymupdf.open(stream=data, filetype="pdf") as pdf:
                    text = "\n\n".join(page.get_text("text") for page in pdf)
            except Exception:
                raise ValueError("That PDF could not be read.") from err
    elif suffix == ".docx":
        try:
            from docx import Document
            document = Document(io.BytesIO(data))
            blocks = [paragraph.text for paragraph in document.paragraphs]
            for table in document.tables:
                for row in table.rows:
                    blocks.append("\t".join(cell.text for cell in row.cells))
            text = "\n".join(block for block in blocks if block)
        except ImportError:
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    xml = archive.read("word/document.xml").decode("utf-8", "replace")
                text = "\n".join(
                    "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", paragraph))
                    for paragraph in re.findall(r"<w:p(?: [^>]*)?>(.*?)</w:p>", xml)
                    if re.search(r"<w:t[^>]*>", paragraph)
                )
            except (KeyError, zipfile.BadZipFile) as err:
                raise ValueError("That DOCX could not be read.") from err
        except Exception as err:
            raise ValueError("That DOCX could not be read.") from err
    else:
        text = data.decode("utf-8", "replace")
    text = text.strip()
    if not text:
        raise ValueError("That file has no readable text.")
    return text


def coverage(query: str, chunk: str) -> float:
    """Share of query words found in the chunk (4-letter prefix match, so burns ~ burnt)."""
    q = {t[:4] for t in tokenize(query)}
    c = {t[:4] for t in tokenize(chunk)}
    return len(q & c) / len(q) if q else 0.0


class Pantry:
    def __init__(self, engine, path: Path | None = None, chunk_words=120, chunk_overlap=20):
        self.engine, self.path = engine, path
        self.size, self.overlap = chunk_words, chunk_overlap
        self.docs: dict[str, Document] = {}
        self._load()

    def add(self, name: str, text: str) -> Document:
        name, text = name.strip()[:120] or "untitled", text.strip()
        if not text:
            raise ValueError("That file is empty.")
        if len(text) > MAX_CHARS:
            raise ValueError(f"Too big: keep it under {MAX_CHARS:,} characters.")
        doc = Document(uuid.uuid4().hex[:8], name, text, self.engine.chunk(text, self.size, self.overlap))
        self.docs[doc.id] = doc
        self._save()
        return doc

    def add_file(self, name: str, data: bytes) -> Document:
        return self.add(name, extract_text(name, data))

    def remove(self, doc_id: str) -> bool:
        if doc_id not in self.docs:
            return False
        remaining = {key: doc for key, doc in self.docs.items() if key != doc_id}
        self._save(remaining)
        self.docs.clear()
        self.docs.update(remaining)
        return True

    def listing(self) -> list[dict]:
        return [{"id": d.id, "name": d.name, "chunks": len(d.chunks), "chars": len(d.text)} for d in self.docs.values()]

    def summary_chunks(self, query: str, k: int) -> list[Hit]:
        topic = set(tokenize(query)) - SUMMARY_WORDS
        named_docs = [
            doc for doc in self.docs.values()
            if topic and topic.issubset(set(tokenize(doc.name)))
        ]
        if named_docs:
            return [Hit(doc.id, doc.name, chunk, 0.0) for doc in named_docs for chunk in doc.chunks]
        if topic:
            matches = self.search(query, k)
            if matches:
                return matches
        return [Hit(doc.id, doc.name, chunk, 0.0) for doc in self.docs.values() for chunk in doc.chunks]

    def search(self, query: str, k: int, min_coverage: float = MIN_COVERAGE) -> list[Hit]:
        flat = [(d, c) for d in self.docs.values() for c in d.chunks]
        ranked = self.engine.rank(query, [c for _, c in flat], k)
        hits = [Hit(flat[i][0].id, flat[i][0].name, flat[i][1], score) for i, score in ranked]
        # Lexical search will happily match one stray word ("cup"). Drop weak matches so the Saucier can say "not in the pantry".
        return [h for h in hits if coverage(query, h.text) >= min_coverage]

    def _save(self, docs=None):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            documents = self.docs.values() if docs is None else docs.values()
            payload = [{"id": d.id, "name": d.name, "text": d.text} for d in documents]
            temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
            try:
                temporary.write_text(json.dumps(payload), encoding="utf-8")
                temporary.replace(self.path)
            finally:
                if temporary.exists():
                    temporary.unlink()

    def _load(self):
        if self.path and self.path.exists():
            for row in json.loads(self.path.read_text(encoding="utf-8")):
                self.docs[row["id"]] = Document(
                    row["id"], row["name"], row["text"], self.engine.chunk(row["text"], self.size, self.overlap)
                )
