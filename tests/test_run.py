import argparse
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests import helpers  # noqa: F401
import run as launcher


class SetupCommandTests(unittest.TestCase):
    def setUp(self):
        self.args = argparse.Namespace(
            port=8000,
            engine="python",
            demo=False,
            allow_origin=None,
            no_browser=True,
        )
        self.settings = SimpleNamespace(engine="python", ollama_host="http://127.0.0.1:11434")
        self.hardware = {
            "os": "windows",
            "arch": "AMD64",
            "cores": 4,
            "ram_mb": 8192,
            "vram_mb": 0,
            "gpu": None,
        }
        self.engine = Mock()
        self.engine.hardware.return_value = self.hardware
        self.model = "llama3.2:3b"

    def test_installs_ollama_then_launches_when_user_accepts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(launcher, "ROOT", Path(temp_dir)),
                patch("spaghetti.config.Settings", return_value=self.settings),
                patch("spaghetti.engine.load_engine", return_value=self.engine),
                patch("spaghetti.runtimes.ollama.status", return_value={"state": "missing", "installed": []}),
                patch(
                    "spaghetti.runtimes.ollama.start",
                    return_value={"state": "running", "installed": [self.model]},
                ),
                patch("builtins.input", return_value="y"),
                patch("subprocess.run", return_value=SimpleNamespace(returncode=0)) as run_script,
                patch.object(launcher, "cmd_serve") as serve,
            ):
                launcher.cmd_setup(self.args)

            self.assertTrue((Path(temp_dir) / "spaghetti-setup.bat").is_file())
            run_script.assert_called_once()
            serve.assert_called_once_with(self.args)

    def test_downloads_missing_model_before_launching(self):
        status = Mock(
            side_effect=[
                {"state": "running", "installed": []},
                {"state": "running", "installed": [self.model]},
            ]
        )
        pull = Mock(return_value=iter([{"type": "progress", "status": "pulling", "percent": 100}, {"type": "done"}]))
        with (
            patch("spaghetti.config.Settings", return_value=self.settings),
            patch("spaghetti.engine.load_engine", return_value=self.engine),
            patch("spaghetti.runtimes.ollama.status", status),
            patch("spaghetti.runtimes.ollama.start", return_value={"state": "running", "installed": []}),
            patch("spaghetti.runtimes.ollama.pull", pull),
            patch("builtins.input", return_value="y"),
            patch.object(launcher, "cmd_serve") as serve,
        ):
            launcher.cmd_setup(self.args)

        pull.assert_called_once_with(self.settings.ollama_host, self.model)
        serve.assert_called_once_with(self.args)


if __name__ == "__main__":
    unittest.main()
