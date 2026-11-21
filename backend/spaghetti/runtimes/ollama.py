"""Models run on the user's device through Ollama (https://ollama.com). Streaming + keep-alive for speed."""
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from .base import ModelError, post_json

KEEP_ALIVE = "30m"  # keep the model in memory between questions: no reload delay
OPTIONS = {"temperature": 0.2, "num_ctx": 4096}


def find_binary() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    candidates = [Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
                  Path("/Applications/Ollama.app/Contents/Resources/ollama"), Path("/usr/local/bin/ollama")]
    return next((str(c) for c in candidates if c.is_file()), None)


def _open(url: str, payload: dict, timeout: int):
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json"}, method="POST")
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as err:
        if err.code == 404:
            raise ModelError("That model is not downloaded yet.", "model_missing") from None
        raise ModelError(f"Ollama answered HTTP {err.code}.") from None
    except (urllib.error.URLError, ConnectionError):
        raise ModelError("Ollama is not running.", "ollama_down") from None


class Ollama:
    def __init__(self, host: str):
        self.host = host.rstrip("/")

    def _payload(self, messages, model, stream):
        return {"model": model, "messages": messages, "stream": stream, "keep_alive": KEEP_ALIVE, "options": OPTIONS}

    def chat(self, messages, model):
        data = post_json(f"{self.host}/api/chat", self._payload(messages, model, False))
        try:
            return data["message"]["content"].strip()
        except (KeyError, TypeError):
            raise ModelError("Unexpected reply from Ollama.") from None

    def chat_stream(self, messages, model):
        """Yield text pieces as they are generated. Newer Ollama sends thinking separately: re-wrap it in <think> tags."""
        thinking = False
        with _open(f"{self.host}/api/chat", self._payload(messages, model, True), 600) as resp:
            for line in resp:
                if not line.strip():
                    continue
                row = json.loads(line)
                if "error" in row:
                    raise ModelError(str(row["error"]))
                msg = row.get("message", {})
                if msg.get("thinking"):
                    yield ("" if thinking else "<think>") + msg["thinking"]
                    thinking = True
                if msg.get("content"):
                    yield ("</think>" if thinking else "") + msg["content"]
                    thinking = False
                if row.get("done"):
                    return


def status(host: str) -> dict:
    """state: running | installed (not running) | missing."""
    try:
        with urllib.request.urlopen(host + "/api/tags", timeout=2) as r:
            names = [m["name"] for m in json.loads(r.read()).get("models", [])]
        return {"state": "running", "installed": names}
    except (urllib.error.URLError, OSError, ValueError):
        return {"state": "installed" if find_binary() else "missing", "installed": []}


def start(host: str, wait: float = 10.0) -> dict:
    binary = find_binary()
    if binary and status(host)["state"] != "running":
        subprocess.Popen([binary, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.time() + wait
        while time.time() < deadline and status(host)["state"] != "running":
            time.sleep(0.5)
    return status(host)


def warm(host: str, model: str) -> bool:
    """Load the model into memory now, so the first question is fast."""
    try:
        with _open(f"{host}/api/generate", {"model": model, "keep_alive": KEEP_ALIVE}, 120):
            return True
    except ModelError:
        return False


def pull(host: str, model: str):
    try:
        with _open(host + "/api/pull", {"model": model, "stream": True}, 3600) as resp:
            for line in resp:
                row = json.loads(line)
                if "error" in row:
                    yield {"type": "error", "message": row["error"]}
                    return
                total, done = row.get("total"), row.get("completed")
                yield {"type": "progress", "status": row.get("status", ""), "percent": round(100 * done / total) if total and done else None}
        yield {"type": "done"}
    except ModelError as err:
        yield {"type": "error", "message": str(err)}
