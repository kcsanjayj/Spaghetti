"""Settings come from environment variables only, read when Settings() is created (so CLI flags set later still apply)."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def load_environment(path: Path | None = None) -> None:
    load_dotenv(path or ROOT / ".env", override=False)


load_environment()


def _env(name: str, default: str, cast=str):
    return field(default_factory=lambda: cast(os.getenv(name, default)))


def _data_dir() -> Path:
    path = Path(os.getenv("SPAGHETTI_DATA", "data")).expanduser()
    return path if path.is_absolute() else ROOT / path


@dataclass(frozen=True)
class Settings:
    host: str = _env("SPAGHETTI_HOST", "127.0.0.1")  # local only by default
    port: int = _env("SPAGHETTI_PORT", "8000", int)
    data_dir: Path = field(default_factory=_data_dir)
    ollama_host: str = _env("OLLAMA_HOST", "http://127.0.0.1:11434")
    engine: str = _env("SPAGHETTI_ENGINE", "auto")  # auto | rust | python
    demo: bool = field(default_factory=lambda: os.getenv("SPAGHETTI_DEMO", "0") == "1")  # enables the offline mock model
    # Web pages allowed to call this local backend (e.g. the UI hosted on Cloudflare Pages). Explicit origins only, never "*".
    allow_origins: tuple = field(default_factory=lambda: tuple(o.strip().rstrip("/") for o in os.getenv("SPAGHETTI_ALLOW_ORIGIN", "").split(",") if o.strip()))
    pass_score: float = 7.0  # Taster score needed to serve without retry
    max_retries: int = 1  # bounded self-correction: never loops forever
    chunk_words: int = 120
    chunk_overlap: int = 20
    max_body_bytes: int = 20_000_000
