import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.config import settings
from scripts.prepare_installation import prepare


class TestPublicSetup(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="localasr-setup-fixture-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.site = self.base / "environment/site-packages"
        self.site.mkdir(parents=True)
        self.model = self.base / "model"
        self.model.mkdir()
        for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"):
            (self.model / name).write_bytes(b"SYNTHETIC-NOT-EXECUTABLE")
        python = self.base / "interpreter/python.exe"
        python.parent.mkdir()
        python.write_bytes(b"SYNTHETIC-NOT-EXECUTABLE")
        self.config = {"python": str(python), "site_packages": str(self.site),
                       "model_path": str(self.model), "revision": "a" * 40,
                       "device": "cpu", "compute_type": "int8",
                       "profiles": {"auto": {"language": None, "task": "transcribe", "label": "Auto"}}}
        self.output = self.base / "candidate"
        self.distributions = [SimpleNamespace(metadata={"Name": name}, version="0.0.synthetic")
                              for name in ("faster-whisper", "ctranslate2", "av", "numpy", "reportlab", "pillow")]
        stub = patch("scripts.prepare_installation.importlib.metadata.distributions", return_value=self.distributions)
        stub.start()
        self.addCleanup(stub.stop)

    def test_prepare_never_approves_or_executes(self):
        result = prepare(self.config, self.output)
        self.assertFalse(result["approved"])
        self.assertFalse((self.output / "approval.json").exists())
        grant = json.loads((self.output / "approval.pending.json").read_text("utf-8"))
        self.assertFalse(grant["approved"])
        self.assertEqual(grant["inventory_sha256"], hashlib.sha256((self.output / "inventory.json").read_bytes()).hexdigest())
        inventory = json.loads((self.output / "inventory.json").read_text("utf-8"))
        self.assertEqual(len(inventory["files"]), 5)
        for item in inventory["files"]:
            self.assertEqual(item["sha256"], hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest())

    def test_existing_destination_is_preserved(self):
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("SYNTHETIC", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "NEW_SEPARATE_OUTPUT_REQUIRED"):
            prepare(self.config, self.output)
        self.assertEqual(sentinel.read_text("utf-8"), "SYNTHETIC")

    def test_missing_model_does_not_write_candidate(self):
        (self.model / "model.bin").unlink()
        with self.assertRaisesRegex(ValueError, "MODEL_MISSING"):
            prepare(self.config, self.output)
        self.assertFalse(self.output.exists())

    def test_missing_dependency_does_not_write_candidate(self):
        self.distributions.pop()
        with self.assertRaisesRegex(ValueError, "DEPENDENCIES_MISSING"):
            prepare(self.config, self.output)
        self.assertFalse(self.output.exists())

    def test_placeholder_revision_is_refused(self):
        self.config["revision"] = "REPLACE_WITH_VERIFIED_MODEL_REVISION"
        with self.assertRaisesRegex(ValueError, "VERIFIED_MODEL_REVISION_REQUIRED"):
            prepare(self.config, self.output)
        self.assertFalse(self.output.exists())

    def test_older_local_profile_gets_generic_alias_without_file_change(self):
        self.config["profiles"] = {"old-local-key": {"language": None, "task": "transcribe", "label": "Old local label"}}
        file = self.base / "local.json"
        file.write_text(json.dumps(self.config), encoding="utf-8")
        before = file.read_bytes()
        with patch("app.config.runtime_paths", return_value=(file, None, None)):
            loaded = settings()
        self.assertIn("old-local-key", loaded["profiles"])
        self.assertEqual(loaded["profiles"]["auto"]["label"], "Détection automatique")
        self.assertEqual(file.read_bytes(), before)
