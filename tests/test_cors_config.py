import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from tests import helpers  # noqa: F401
from spaghetti.api.server import make_server
from spaghetti.config import ROOT, Settings, load_environment
from spaghetti.engine.python_engine import PythonEngine
from spaghetti.pantry import Pantry

ALLOWED = "https://spaghetti.pages.dev"


class SettingsTests(unittest.TestCase):
    def test_dotenv_settings_resolve_paths_and_preserve_process_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.env"
            path.write_text("SPAGHETTI_PORT=9123\nSPAGHETTI_DATA=./isolated-data\n", encoding="utf-8")
            with patch.dict(os.environ, {"SPAGHETTI_PORT": "7654"}):
                os.environ.pop("SPAGHETTI_DATA", None)
                load_environment(path)
                settings = Settings()

            self.assertEqual(settings.port, 7654)
            self.assertEqual(settings.data_dir, ROOT / "isolated-data")

    def test_env_is_read_when_settings_is_created_not_at_import(self):
        old = {k: os.environ.get(k) for k in ("SPAGHETTI_PORT", "SPAGHETTI_DEMO", "SPAGHETTI_ALLOW_ORIGIN")}
        try:
            os.environ.update(SPAGHETTI_PORT="9123", SPAGHETTI_DEMO="1", SPAGHETTI_ALLOW_ORIGIN=f"{ALLOWED}/, http://a.test")
            s = Settings()
            self.assertEqual((s.port, s.demo, s.allow_origins), (9123, True, (ALLOWED, "http://a.test")))
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def test_no_origins_allowed_by_default(self):
        self.assertEqual(Settings().allow_origins, ())


class CorsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(Settings(port=0, allow_origins=(ALLOWED,)), PythonEngine(), Pantry(PythonEngine()))
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def req(self, path, origin=None, method="GET", headers=None):
        h = dict(headers or {})
        if origin:
            h["Origin"] = origin
        try:
            with urllib.request.urlopen(urllib.request.Request(self.base + path, method=method, headers=h)) as r:
                return r.status, r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.headers

    def test_allowed_origin_gets_exact_origin_back_not_a_wildcard(self):
        _, h = self.req("/api/health", ALLOWED)
        self.assertEqual(h["Access-Control-Allow-Origin"], ALLOWED)
        self.assertEqual(h["Vary"], "Origin")

    def test_other_origins_get_no_cors_headers(self):
        for origin in ("https://evil.example", "http://spaghetti.pages.dev", None):
            _, h = self.req("/api/health", origin)
            self.assertIsNone(h["Access-Control-Allow-Origin"], origin)

    def test_preflight_including_chrome_private_network_header(self):
        code, h = self.req("/api/ask", ALLOWED, "OPTIONS", {"Access-Control-Request-Private-Network": "true", "Access-Control-Request-Method": "POST"})
        self.assertEqual(code, 204)
        self.assertEqual(h["Access-Control-Allow-Private-Network"], "true")
        self.assertIn("POST", h["Access-Control-Allow-Methods"])

    def test_head_requests_are_answered(self):
        self.assertEqual(self.req("/api/health", method="HEAD")[0], 200)

    def test_preflight_from_a_stranger_gets_nothing(self):
        code, h = self.req("/api/ask", "https://evil.example", "OPTIONS")
        self.assertEqual(code, 204)
        self.assertIsNone(h["Access-Control-Allow-Origin"])


if __name__ == "__main__":
    unittest.main()


class SecurityHeaderTests(unittest.TestCase):
    def test_pages_headers_file_and_server_use_the_same_csp(self):
        from spaghetti.api.server import SECURITY_HEADERS
        from spaghetti.config import ROOT
        pages = (ROOT / "frontend" / "_headers").read_text()
        self.assertIn(SECURITY_HEADERS["Content-Security-Policy"], pages)
        self.assertNotIn("unsafe-eval", pages)
        self.assertNotIn("script-src 'self' 'unsafe-inline'", pages)

    def test_index_has_no_inline_script(self):
        from spaghetti.config import ROOT
        html = (ROOT / "frontend" / "index.html").read_text()
        self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)[^>]*>")
