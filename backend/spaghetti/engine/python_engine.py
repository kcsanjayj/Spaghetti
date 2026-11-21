"""Pure-Python twin of core-rust/src/text.rs. Used when Rust is not built."""
import math
import os
import platform
import re
import shutil
import subprocess
from collections import Counter

STOP = set(
    "the is are was were an of to in on and or for with what which who how does do did it its "
    "this that be as at by from me my about can you tell".split()
)
K1, B = 1.5, 0.75
_TOKEN = re.compile(r"[^\W_]+")


def tokenize(s: str) -> list[str]:
    return [t for t in _TOKEN.findall(s.lower()) if len(t) >= 2 and t not in STOP]


class PythonEngine:
    name = "python"

    def chunk(self, text, size=120, overlap=20):
        words, size = text.split(), max(size, 1)
        step, out, start = max(size - overlap, 1), [], 0
        while start < len(words):
            end = min(start + size, len(words))
            out.append(" ".join(words[start:end]))
            if end == len(words):
                break
            start += step
        return out

    def rank(self, query, chunks, k=4):
        docs = [tokenize(c) for c in chunks]
        if not docs:
            return []
        n, avg = len(docs), sum(map(len, docs)) / len(docs)
        df = Counter(t for d in docs for t in set(d))
        scored = []
        for i, d in enumerate(docs):
            tf, s = Counter(d), 0.0
            for t in set(tokenize(query)):
                if not tf[t]:
                    continue
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                norm = 1 - B + B * len(d) / avg if avg else 1.0
                s += idf * tf[t] * (K1 + 1) / (tf[t] + K1 * norm)
            if s > 0:
                scored.append((i, s))
        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored[:k]

    def overlap(self, answer, context):
        a = set(tokenize(answer))
        return len(a & set(tokenize(context))) / len(a) if a else 0.0

    def hardware(self):
        return probe_hardware()


def _run(*cmd: str) -> str | None:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return done.stdout.strip() if done.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def probe_hardware() -> dict:
    """Pure-Python twin of core-rust/src/hw.rs (same keys, same units)."""
    osname = {"darwin": "macos"}.get(platform.system().lower(), platform.system().lower())
    arch = {"arm64": "aarch64", "amd64": "x86_64"}.get(platform.machine().lower(), platform.machine().lower())
    ram = 0
    if osname == "linux" and os.path.exists("/proc/meminfo"):
        line = next((l for l in open("/proc/meminfo") if l.startswith("MemTotal:")), "")
        ram = int(line.split()[1]) // 1024 if line else 0
    elif osname == "macos":
        ram = int(_run("sysctl", "-n", "hw.memsize") or 0) // 1_048_576
    elif osname == "windows":
        ram = int(_run("powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory") or 0) // 1_048_576
    gpu, vram = "", 0
    smi = _run("nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits") if shutil.which("nvidia-smi") else None
    if smi:
        name, _, mem = smi.splitlines()[0].partition(",")
        gpu, vram = name.strip(), int(mem.strip() or 0)
    return {"os": osname, "arch": arch, "cores": os.cpu_count() or 1, "ram_mb": ram, "gpu": gpu,
            "vram_mb": vram, "unified": int(osname == "macos" and arch == "aarch64")}
