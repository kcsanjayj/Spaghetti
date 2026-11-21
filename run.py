#!/usr/bin/env python3
"""🍝 Spaghetti: the one file that runs the whole project.

    python run.py                 start the kitchen and open the browser
    python run.py build           compile the Rust core (needs https://rustup.rs)
    python run.py test            run all tests
    python run.py eval            run the evaluation harness (offline demo model)
    python run.py setup           pick a model for this device and write a one-click Ollama setup script
    python run.py check           show what is installed (Python, Rust, Ollama)

Options for the default command:  --port 8000  --demo  --no-browser  --engine auto|rust|python  --allow-origin https://your-ui.pages.dev
Python 3.10+ is the only requirement. Rust is optional: without it a pure-Python engine takes over.
No API keys, no cloud: models run on your device through Ollama.
"""
import argparse
import errno
import os
import shutil
import subprocess
import sys
import threading
import unittest
import webbrowser
from pathlib import Path


def _configure_console():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


_configure_console()

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

# Load project-local settings before argparse reads defaults from the environment.
from spaghetti.config import load_environment  # noqa: E402

load_environment()


def build_rust(verbose=True) -> bool:
    if not shutil.which("cargo"):
        if verbose:
            print("ℹ️  Rust (cargo) not found. Using the pure-Python engine. Install Rust from https://rustup.rs for the fast one.")
        return False
    print("🦀 Compiling the Rust core (first time only)...")
    done = subprocess.run(["cargo", "build", "--release", "--quiet"], cwd=ROOT / "core-rust")
    print("✅ Rust core ready." if done.returncode == 0 else "⚠️  Rust build failed; falling back to Python.")
    return done.returncode == 0


def cmd_serve(args):
    from spaghetti.engine.loader import find_binary
    if args.engine != "python" and not find_binary():
        build_rust()
    os.environ.update(SPAGHETTI_PORT=str(args.port), SPAGHETTI_ENGINE=args.engine)
    if args.demo:
        os.environ["SPAGHETTI_DEMO"] = "1"
    if args.allow_origin:
        os.environ["SPAGHETTI_ALLOW_ORIGIN"] = ",".join(args.allow_origin)
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, [f"http://127.0.0.1:{args.port}"]).start()
    from spaghetti.__main__ import main
    try:
        main()
    except OSError as err:
        if err.errno == errno.EADDRINUSE or getattr(err, "winerror", None) == 10048:
            print(
                f"Port {args.port} is already in use. If Spaghetti is already running, open "
                f"http://127.0.0.1:{args.port}; otherwise choose another port with --port.",
                file=sys.stderr,
            )
            raise SystemExit(2) from err
        raise


def cmd_test(_):
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    sys.exit(not unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful())


def cmd_eval(args):
    from eval.harness import main
    sys.exit(main(args.rest))


def _download_model(ollama, host: str, tag: str) -> None:
    print(f"⬇️  Downloading {tag} (this may take a while the first time)...")
    finished = False
    line_width = 0
    for event in ollama.pull(host, tag):
        if event["type"] == "error":
            raise SystemExit(f"Ollama could not download the model: {event['message']}")
        if event["type"] == "done":
            finished = True
            break
        if event["type"] == "progress":
            status = event.get("status", "")
            percent = event.get("percent")
            line = f"{status} ({percent}%)" if percent is not None else status
            print(f"\r{line.ljust(line_width)}", end="", flush=True)
            line_width = max(line_width, len(line))
    if not finished:
        raise SystemExit("Ollama stopped the model download before it finished.")
    if line_width:
        print()
    print(f"✅ {tag} is ready.")


def cmd_setup(args):
    """Install or start Ollama, download a suitable model, then launch Spaghetti."""
    from spaghetti.advisor.catalog import recommend_default
    from spaghetti.advisor.scripts import make_script
    from spaghetti.config import Settings
    from spaghetti.engine import load_engine
    from spaghetti.runtimes import ollama
    settings = Settings()
    hw = load_engine(settings.engine).hardware()
    st = ollama.status(settings.ollama_host)
    ram, vram = hw["ram_mb"] / 1024, hw["vram_mb"] / 1024
    tag = recommend_default(ram, vram)
    print(f"💻 {hw['os']} {hw['arch']} | {hw['cores']} cores | {ram:.1f} GB RAM | GPU: {hw['gpu'] or 'none detected'}")
    print(f"🏠 Ollama: {st['state']}   🎯 Recommended model: {tag}")
    if st["state"] == "missing":
        name, content = make_script("windows" if hw["os"] == "windows" else "unix", [tag])
        path = ROOT / name
        path.write_text(content, encoding="utf-8")
        print(f"📝 Wrote {path.name}. It will install Ollama and download {tag}.")
        if input("Run setup now? [y/N] ").strip().lower() != "y":
            print(f"Setup paused. Run {path.name} when you're ready, then run python run.py.")
            return
        result = subprocess.run(
            ["cmd", "/c", str(path)] if hw["os"] == "windows" else ["bash", str(path)],
            cwd=ROOT,
        )
        if result.returncode:
            raise SystemExit(f"Ollama setup failed with exit code {result.returncode}.")

    st = ollama.start(settings.ollama_host)
    if st["state"] != "running":
        raise SystemExit("Ollama is not running. Install it from https://ollama.com/download and try again.")
    if tag not in st["installed"]:
        print(f"Model {tag} is not downloaded yet.")
        if input("Download it now? [y/N] ").strip().lower() != "y":
            print("Setup paused. Run python run.py setup when you're ready to download the model.")
            return
        _download_model(ollama, settings.ollama_host, tag)
        st = ollama.status(settings.ollama_host)
        if tag not in st["installed"]:
            raise SystemExit(f"Ollama did not confirm that {tag} was installed.")

    print("✅ Setup complete. Starting Spaghetti...")
    cmd_serve(args)


def cmd_check(_):
    from spaghetti.engine.loader import find_binary
    from spaghetti.config import Settings
    from spaghetti.runtimes import ollama as local_models
    print(f"🐍 Python  {sys.version.split()[0]}")
    print(f"🦀 Rust    {'binary found' if find_binary() else 'not built (python engine will be used)'}  | cargo: {bool(shutil.which('cargo'))}")
    st = local_models.status(Settings().ollama_host)
    print(f"🏠 Ollama  {st['state']}" + (f", models: {', '.join(st['installed']) or 'none yet'}" if st['state'] == 'running' else ''))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="serve", choices=["serve", "build", "test", "eval", "check", "setup"])
    ap.add_argument("--port", type=int, default=int(os.getenv("SPAGHETTI_PORT", "8000")))
    ap.add_argument("--demo", action="store_true", help="add the offline mock model (for trying the UI without downloading a model)")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--allow-origin", action="append", help="let a hosted UI (e.g. https://spaghetti.pages.dev) call this local backend; repeatable")
    ap.add_argument("--engine", default=os.getenv("SPAGHETTI_ENGINE", "auto"), choices=["auto", "rust", "python"])
    args, args.rest = ap.parse_known_args()
    {"serve": cmd_serve, "build": lambda a: build_rust(), "test": cmd_test, "eval": cmd_eval, "check": cmd_check, "setup": cmd_setup}[args.command](args)


if __name__ == "__main__":
    main()
