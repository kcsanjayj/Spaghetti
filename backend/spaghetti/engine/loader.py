"""Pick the engine: Rust if the binary exists, otherwise Python. Never crash."""
import os
import shutil

from ..config import ROOT
from .python_engine import PythonEngine
from .rust_engine import RustEngine


def find_binary() -> str | None:
    exe = "spaghetti-core.exe" if os.name == "nt" else "spaghetti-core"
    path = ROOT / "core-rust" / "target" / "release" / exe
    return str(path) if path.exists() else shutil.which("spaghetti-core")


def load_engine(prefer: str = "auto"):
    if prefer != "python":
        binary = find_binary()
        if binary:
            try:
                engine = RustEngine(binary)
                engine.overlap("ok", "ok")  # smoke test
                return engine
            except Exception:
                if prefer == "rust":
                    raise
    return PythonEngine()
