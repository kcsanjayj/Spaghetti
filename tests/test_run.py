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


class ServeCommandTests(unittest.TestCase):
    def setUp(self):
        self.args = argparse.Namespace(
            port=8000,
            engine="python",
            demo=False,
            allow_origin=None,
            no_browser=True,
        )

    def test_starts_ollama_before_serving(self):
        with (
            patch("spaghetti.engine.loader.find_binary", return_value="spaghetti-core"),
            patch("threading.Thread") as thread,
            patch("spaghetti.__main__.main") as serve,
        ):
            launcher.cmd_serve(self.args)

        thread.assert_called_once_with(
            target=launcher._start_ollama,
            args=("http://127.0.0.1:11434",),
            name="ollama-start",
            daemon=True,
        )
        thread.return_value.start.assert_called_once_with()
        serve.assert_called_once_with()

    def test_demo_mode_does_not_start_ollama(self):
        self.args.demo = True
        with (
            patch("spaghetti.engine.loader.find_binary", return_value="spaghetti-core"),
            patch("threading.Thread") as thread,
            patch("spaghetti.__main__.main"),
        ):
            launcher.cmd_serve(self.args)

        thread.assert_not_called()

    def test_ollama_start_errors_are_reported_without_blocking_startup(self):
        with (
            patch("spaghetti.runtimes.ollama.start", side_effect=OSError("launch failed")),
            patch("sys.stderr") as stderr,
        ):
            launcher._start_ollama("http://127.0.0.1:11434")

        stderr.write.assert_called()


class OllamaStartupTests(unittest.TestCase):
    def test_does_not_spawn_a_second_server_when_already_running(self):
        from spaghetti.runtimes import ollama

        with (
            patch("spaghetti.runtimes.ollama.find_binary", return_value="ollama"),
            patch(
                "spaghetti.runtimes.ollama.status",
                return_value={"state": "running", "installed": []},
            ),
            patch("spaghetti.runtimes.ollama.subprocess.Popen") as popen,
        ):
            status = ollama.start("http://127.0.0.1:11434")

        self.assertEqual(status["state"], "running")
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
