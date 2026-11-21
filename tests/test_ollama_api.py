import json
import base64
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

from tests import helpers  # noqa: F401
from spaghetti.api.server import make_server
from spaghetti.config import Settings
from spaghetti.engine.loader import find_binary
from spaghetti.engine.python_engine import PythonEngine, probe_hardware
from spaghetti.engine.rust_engine import RustEngine
from spaghetti.pantry import Pantry
from spaghetti.runtimes import ollama


class FakeOllama(BaseHTTPRequestHandler):
    """Speaks just enough of Ollama's API: /api/tags, /api/chat (stream + not), /api/generate, /api/pull."""
    def log_message(self, *_):
        pass

    def _ok(self, data):
        raw = json.dumps(data).encode()
        self.send_response(200); self.end_headers(); self.wfile.write(raw)

    def do_GET(self):
        self._ok({"models": [{"name": "llama3.2:1b"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/generate":
            return self._ok({"done": True})
        if self.path == "/api/chat":
            if body["model"] == "ghost:1b":
                self.send_response(404); self.end_headers(); return
            if not body.get("stream"):
                return self._ok({"message": {"content": '{"score": 9, "issues": ""}'}})
            self.send_response(200); self.end_headers()
            for piece in ({"thinking": "hm"}, {"content": "Eight "}, {"content": "minutes. [1]"}):
                self.wfile.write((json.dumps({"message": piece, "done": False}) + "\n").encode())
            self.wfile.write(b'{"message":{"content":""},"done":true}\n')
            return
        self.send_response(200); self.end_headers()
        for row in ({"status": "pulling", "total": 100, "completed": 40}, {"status": "success"}):
            self.wfile.write((json.dumps(row) + "\n").encode())


class Base(unittest.TestCase):
    @classmethod
    def boot(cls, ollama_host=None):
        cls.fake = HTTPServer(("127.0.0.1", 0), FakeOllama)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        settings = Settings(port=0, demo=True, ollama_host=ollama_host or f"http://127.0.0.1:{cls.fake.server_port}")
        pantry = Pantry(PythonEngine())
        pantry.add("a.txt", "Boil spaghetti for eight minutes in salted water.")
        cls.server = make_server(settings, PythonEngine(), pantry)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.fake.shutdown()

    def call(self, path, body=None, method=None):
        req = urllib.request.Request(self.base + path, json.dumps(body).encode() if body is not None else None, method=method)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def ask(self, **body):
        _, text = self.call("/api/ask", {"question": "how long to boil spaghetti?", "model": "llama3.2:1b", **body})
        return [json.loads(l) for l in text.splitlines() if l.startswith("{")]


class OllamaTests(Base):
    @classmethod
    def setUpClass(cls):
        cls.boot()

    def test_streamed_answer_arrives_as_tokens_then_final_with_thinking_split(self):
        events = self.ask()
        self.assertEqual(events[-1]["type"], "final")
        self.assertEqual(events[-1]["answer"], "Eight minutes. [1]")
        self.assertEqual(events[-1]["thoughts"], "hm")
        tokens = [e for e in events if e["type"] == "token"]
        self.assertEqual("".join(t["text"] for t in tokens if t["kind"] == "answer"), "Eight minutes. [1]")

    def test_careful_mode_adds_the_judge(self):
        final = self.ask(careful=True)[-1]
        self.assertEqual((final["careful"], final["score"]), (True, 9.0))

    def test_missing_model_gives_a_code_for_the_ui(self):
        self.assertEqual(self.ask(model="ghost:1b")[-1]["code"], "model_missing")

    def test_no_model_selected_is_a_friendly_coded_error(self):
        self.assertEqual(self.ask(model="")[-1]["code"], "no_model")

    def test_models_endpoint_lists_installed_catalog_and_recommendation(self):
        d = json.loads(self.call("/api/models")[1])
        self.assertEqual(d["state"], "running")
        self.assertIn("llama3.2:1b", d["installed"])
        self.assertTrue(any(m["recommended"] for m in d["catalog"]))

    def test_warm_and_pull(self):
        self.assertTrue(json.loads(self.call("/api/warm", {"model": "llama3.2:1b"})[1])["ok"])
        events = list(ollama.pull(f"http://127.0.0.1:{self.fake.server_port}", "qwen3:1.7b"))
        self.assertEqual((events[0]["percent"], events[-1]["type"]), (40, "done"))

    def test_pull_rejects_names_outside_the_menu(self):
        self.assertEqual(self.call("/api/models/pull", {"model": "evil/model"})[0], 400)

    def test_setup_script_download_and_injection_block(self):
        code, body = self.call("/api/setup-script?os=linux&models=qwen3:1.7b")
        self.assertEqual(code, 200)
        self.assertIn("ollama pull qwen3:1.7b", body)
        self.assertEqual(self.call("/api/setup-script?os=linux&models=x;rm%20-rf%20~")[0], 400)

    def test_path_traversal_blocked(self):
        self.assertEqual(self.call("/../backend/spaghetti/config.py")[0], 404)

    def test_pantry_roundtrip(self):
        code, body = self.call("/api/pantry", {"name": "b.txt", "text": "Garlic goes in first."})
        self.assertEqual(code, 201)
        self.assertEqual(self.call(f"/api/pantry/{json.loads(body)['id']}", method="DELETE")[0], 200)

    def test_pantry_accepts_base64_docx(self):
        from docx import Document
        document = Document()
        document.add_paragraph("Garlic goes in first.")
        with __import__("io").BytesIO() as output:
            document.save(output)
            encoded = base64.b64encode(output.getvalue()).decode()
        code, body = self.call("/api/pantry", {"name": "recipe.docx", "content_base64": encoded})
        self.assertEqual(code, 201)


class OllamaDownTests(Base):
    @classmethod
    def setUpClass(cls):
        cls.boot(ollama_host="http://127.0.0.1:9")  # nothing listens: Ollama is "stopped"

    def test_ollama_down_is_a_clean_coded_error(self):
        self.assertEqual(self.ask()[-1]["code"], "ollama_down")

    def test_status_is_not_running(self):
        self.assertNotEqual(json.loads(self.call("/api/models")[1])["state"], "running")


@unittest.skipUnless(find_binary(), "Rust core not built")
class HardwareParityTests(unittest.TestCase):
    def test_rust_and_python_agree_on_this_machine(self):
        r, p = RustEngine(find_binary()).hardware(), probe_hardware()
        for key in ("os", "arch", "cores", "unified"):
            self.assertEqual(r[key], p[key], key)
        self.assertAlmostEqual(r["ram_mb"], p["ram_mb"], delta=max(64, p["ram_mb"] * 0.02))


if __name__ == "__main__":
    unittest.main()
