"""Tiny HTTP layer on the standard library. Routes only translate HTTP <-> the kitchen."""
import base64
import binascii
import json
import mimetypes
import re
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .. import __version__
from ..advisor.catalog import CATALOG, OLLAMA_TAGS, fit, recommend_default
from ..advisor.scripts import make_script
from ..config import ROOT, Settings
from ..domain.models import AskRequest
from ..kitchen import Kitchen
from ..runtimes import ModelError
from ..runtimes import ollama as ollama_rt
from ..runtimes.registry import build_model

FRONTEND = ROOT / "frontend"
# Same policy the Cloudflare Pages `_headers` file applies, so local and hosted behave identically.
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; style-src-attr 'unsafe-inline'; img-src 'self' data:; connect-src 'self' http://127.0.0.1:* http://localhost:*; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
}


def make_server(settings: Settings, engine, pantry) -> ThreadingHTTPServer:
    hw_cache: dict = {}

    def hardware() -> dict:
        if not hw_cache:
            hw_cache.update(engine.hardware())
        return hw_cache

    def models_payload() -> dict:
        hw, st = hardware(), ollama_rt.status(settings.ollama_host)
        ram, vram = hw.get("ram_mb", 0) / 1024, hw.get("vram_mb", 0) / 1024
        rec = recommend_default(ram, vram)
        catalog = [{"tag": m.tag, "label": m.label, "size_gb": m.size_gb, "blurb": m.blurb, "reasoning": m.reasoning,
                    "fit": fit(m, ram, vram), "recommended": m.tag == rec, "installed": m.tag in st["installed"]} for m in CATALOG]
        return {"state": st["state"], "installed": st["installed"] + (["mock"] if settings.demo else []), "catalog": catalog, "recommended": rec,
                "hardware": {"ram_gb": round(ram, 1), "cores": hw.get("cores"), "gpu": hw.get("gpu") or ("Apple Silicon" if hw.get("unified") else ""), "os": hw.get("os")}}

    def ask_events(body: dict):
        try:
            llm = build_model(settings, str(body.get("model", "")))
            yield from Kitchen(pantry, engine, llm, str(body.get("model", "")), settings, bool(body.get("careful"))).serve(AskRequest(str(body.get("question", "")).strip(), body.get("history", [])))
        except ModelError as err:
            yield {"type": "error", "message": str(err), "code": err.code}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"  # close after reply => simple streaming

        def log_message(self, *_):
            pass

        def _cors(self):
            """Only origins listed in SPAGHETTI_ALLOW_ORIGIN get CORS headers. Never a wildcard."""
            origin = self.headers.get("Origin", "").rstrip("/")
            if origin and origin in settings.allow_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                if self.headers.get("Access-Control-Request-Private-Network") == "true":  # Chrome: public page -> localhost
                    self.send_header("Access-Control-Allow-Private-Network", "true")

        def do_HEAD(self):  # uptime checkers and link previews use HEAD
            self.send_response(200)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _send(self, body: bytes, ctype: str, status=200, extra: dict | None = None):
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, status=200):
            self._send(json.dumps(data).encode(), "application/json", status)

        def _body(self) -> dict:
            size = int(self.headers.get("Content-Length") or 0)
            if size > settings.max_body_bytes:
                raise ValueError("Request too large.")
            return json.loads(self.rfile.read(size) or b"{}")

        def _stream(self, events):
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            try:
                for ev in events:
                    self.wfile.write((json.dumps(ev) + "\n").encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                events.close()  # the tab went away: stop generating

        def _static(self, path: str):
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (FRONTEND / rel).resolve()
            if FRONTEND.resolve() not in target.parents or not target.is_file():
                return self._json({"error": "not found"}, 404)
            self._send(target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream", extra={"Cache-Control": "no-cache", **SECURITY_HEADERS})

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/api/health":
                return self._json({"ok": True, "version": __version__, "engine": engine.name, "demo": settings.demo})
            if url.path == "/api/models":
                return self._json(models_payload())
            if url.path == "/api/pantry":
                return self._json({"docs": pantry.listing()})
            if url.path == "/api/setup-script":
                q = parse_qs(url.query)
                os_name = (q.get("os") or [hardware().get("os", "linux")])[0]
                tags = [t for t in (q.get("models") or [""])[0].split(",") if t]
                try:
                    name, content = make_script("windows" if os_name == "windows" else "unix", tags)
                except ValueError as err:
                    return self._json({"error": str(err)}, 400)
                return self._send(content.encode(), "text/plain; charset=utf-8", extra={"Content-Disposition": f'attachment; filename="{name}"'})
            self._static(url.path)

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                body = self._body()
                if path == "/api/pantry":
                    name = str(body.get("name", ""))
                    encoded = body.get("content_base64")
                    if encoded is not None:
                        try:
                            data = base64.b64decode(str(encoded), validate=True)
                        except (binascii.Error, ValueError):
                            raise ValueError("Invalid document data.")
                        doc = pantry.add_file(name, data)
                    else:
                        doc = pantry.add(name, str(body.get("text", "")))
                    return self._json({"id": doc.id, "chunks": len(doc.chunks)}, 201)
                if path == "/api/ollama/start":
                    return self._json(ollama_rt.start(settings.ollama_host))
                if path == "/api/warm":
                    return self._json({"ok": ollama_rt.warm(settings.ollama_host, str(body.get("model", ""))) if not (settings.demo and body.get("model") == "mock") else True})
                if path == "/api/models/pull":
                    model = str(body.get("model", ""))
                    if model not in OLLAMA_TAGS:  # only menu models reach Ollama
                        raise ValueError("That model is not in the Spaghetti menu.")
                    return self._stream(ollama_rt.pull(settings.ollama_host, model))
                if path == "/api/ask":
                    if not str(body.get("question", "")).strip():
                        raise ValueError("Ask something first.")
                    if not str(body.get("model", "")).strip():
                        return self._stream(iter([{"type": "error", "message": "Choose a model first.", "code": "no_model"}]))
                    return self._stream(ask_events(body))
                self._json({"error": "not found"}, 404)
            except (ModelError, ValueError) as err:
                self._json({"error": str(err), "code": getattr(err, "code", "bad_request")}, 400)
            except json.JSONDecodeError:
                self._json({"error": "Body must be JSON."}, 400)

        def do_DELETE(self):
            m = re.fullmatch(r"/api/pantry/(\w+)", urlparse(self.path).path)
            if not m:
                return self._json({"error": "not found"}, 404)
            try:
                if pantry.remove(m.group(1)):
                    return self._json({"ok": True})
            except OSError:
                return self._json({
                    "error": "Could not save document removal. The document remains in the pantry.",
                    "code": "storage_error",
                }, 500)
            return self._json({"error": "not found"}, 404)

    class QuietServer(ThreadingHTTPServer):
        daemon_threads = True

        def handle_error(self, request, client_address):
            import sys
            if not isinstance(sys.exc_info()[1], (ConnectionError, BrokenPipeError)):
                super().handle_error(request, client_address)

    return QuietServer((settings.host, settings.port), Handler)
