"""Exercise the Windows entry point using only the current interpreter and fixtures."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == "nt", "Windows command launcher")
class TestCommandLauncher(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="localasr-launch-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "app (test) & spaces"
        self.root.mkdir()
        self.launcher = self.root / "Start LocalASR.cmd"
        shutil.copyfile(Path(__file__).resolve().parents[1] / self.launcher.name, self.launcher)
        self.config = self.root / "runtime/independent/local.json"
        self.config.parent.mkdir(parents=True)
        self.config.write_text(json.dumps({"python": sys.executable}), encoding="utf-8")
        self.result = self.base / "result.json"
        (self.root / "launch.py").write_text(
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['LOCALASR_LAUNCH_TEST_RESULT']).write_text(json.dumps({\n"
            "'args': sys.argv[1:], 'python': sys.executable, 'isolated': sys.flags.isolated,\n"
            "'no_site': sys.flags.no_site, 'no_bytecode': sys.dont_write_bytecode}), encoding='utf-8')\n",
            encoding="utf-8",
        )
        self.env = dict(os.environ)
        self.env.pop("LOCALASR_PYTHON", None)
        self.env["LOCALASR_LAUNCH_TEST_RESULT"] = str(self.result)

    def run_launcher(self, *args):
        command = subprocess.list2cmdline([str(self.launcher), *args])
        return subprocess.run(
            f'"{os.environ["COMSPEC"]}" /d /s /c "{command}"',
            cwd=self.base, env=self.env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
        )

    def test_double_click_uses_local_config_without_environment_variable(self):
        completed = self.run_launcher()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        result = json.loads(self.result.read_text(encoding="utf-8"))
        self.assertEqual(Path(result["python"]), Path(sys.executable))
        self.assertEqual(result["args"], [])
        self.assertEqual((result["isolated"], result["no_site"], result["no_bytecode"]), (1, 1, True))

    def test_arguments_with_spaces_are_forwarded(self):
        args = ["--data-dir", str(self.base / "data (test) & spaces"), "--no-browser"]
        completed = self.run_launcher(*args)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(json.loads(self.result.read_text(encoding="utf-8"))["args"], args)

    def test_explicit_interpreter_is_preserved(self):
        self.config.unlink()
        self.env["LOCALASR_PYTHON"] = sys.executable
        completed = self.run_launcher("--no-browser")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertTrue(self.result.is_file())

    def test_missing_or_invalid_config_fails_without_running_python(self):
        for content in (None, "not json", "{}", '{"python": 12}',
                        json.dumps({"python": str(self.base / "missing.exe")})):
            with self.subTest(content=content):
                if content is None:
                    self.config.unlink(missing_ok=True)
                else:
                    self.config.write_text(content, encoding="utf-8")
                completed = self.run_launcher("--no-browser")
                self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
                self.assertFalse(self.result.exists())
