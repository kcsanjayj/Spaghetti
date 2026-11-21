"""One error type with a machine-readable code, so the UI can offer the right fallback."""
import json
import urllib.error
import urllib.request


class ModelError(Exception):
    """Friendly message + code: ollama_down | model_missing | browser_failed | timeout | failed."""

    def __init__(self, message: str, code: str = "failed"):
        super().__init__(message)
        self.code = code


def post_json(url: str, payload: dict, timeout: int = 300) -> dict:
    request = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as err:
        body = err.read().decode(errors="replace")[:200]
        if err.code == 404:
            raise ModelError("That model is not downloaded on this device yet.", "model_missing") from None
        raise ModelError(f"Ollama answered HTTP {err.code}. {body}") from None
    except (urllib.error.URLError, ConnectionError):
        raise ModelError("Ollama is not running, so the on-device model cannot answer.", "ollama_down") from None
    except TimeoutError:
        raise ModelError("The model took too long. Try a smaller one.", "timeout") from None
