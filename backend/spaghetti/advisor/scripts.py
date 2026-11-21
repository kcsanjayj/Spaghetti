"""One-click setup scripts. They only ever contain tags from our own catalog (no user text reaches a shell)."""
from .catalog import OLLAMA_TAGS


def make_script(os_name: str, tags: list[str]) -> tuple[str, str]:
    """Return (filename, content). Raises ValueError for anything not in the catalog."""
    bad = [t for t in tags if t not in OLLAMA_TAGS]
    if bad or not tags:
        raise ValueError("Unknown model tag.")
    pulls_sh = "\n".join(f'echo "Downloading {t} (one time)..."\nollama pull {t}' for t in tags)
    if os_name == "windows":
        pulls = "\r\n".join(f"echo Downloading {t} (one time)...\r\nollama pull {t}" for t in tags)
        return "spaghetti-setup.bat", (
            "@echo off\r\ntitle Spaghetti setup\r\n"
            "echo This script will: 1) install Ollama if missing  2) start it  3) download your model.\r\n"
            "where ollama >nul 2>nul || (echo Installing Ollama with winget... & winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements)\r\n"
            'set "PATH=%PATH%;%LOCALAPPDATA%\\Programs\\Ollama"\r\n'
            "echo Starting Ollama...\r\nstart \"\" /B ollama serve\r\ntimeout /t 6 >nul\r\n"
            f"{pulls}\r\n"
            'echo.\r\necho Done! Go back to Spaghetti and press "Re-check".\r\npause\r\n')
    return "spaghetti-setup.sh", (
        "#!/usr/bin/env bash\n# Spaghetti setup: 1) install Ollama if missing  2) start it  3) download your model.\nset -e\n"
        'if ! command -v ollama >/dev/null 2>&1; then\n  echo "Installing Ollama..."\n'
        '  if [ "$(uname)" = "Darwin" ]; then\n'
        '    if command -v brew >/dev/null 2>&1; then brew install ollama\n'
        '    else echo "Install the Ollama app from https://ollama.com/download, then run this script again."; exit 1; fi\n'
        "  else\n    curl -fsSL https://ollama.com/install.sh | sh\n  fi\nfi\n"
        'if ! ollama list >/dev/null 2>&1; then\n  echo "Starting Ollama..."\n  (nohup ollama serve >/dev/null 2>&1 &)\n  sleep 4\nfi\n'
        f"{pulls_sh}\n"
        'echo ""\necho "Done! Go back to Spaghetti and press Re-check."\n')
