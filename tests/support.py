"""Synthetic configuration only: never consult a developer's local runtime."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class SyntheticTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        temporary = tempfile.TemporaryDirectory(prefix="localasr-synthetic-")
        cls.addClassCleanup(temporary.cleanup)
        base = Path(temporary.name)
        model = base / "model"
        model.mkdir()
        for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"):
            (model / name).write_bytes(b"SYNTHETIC-NOT-A-MODEL")
        site = base / "site-packages"
        site.mkdir()
        example = Path(__file__).resolve().parents[1] / "models-config/example.json"
        config = json.loads(example.read_text("utf-8"))
        config.update(python=sys.executable, site_packages=str(site), model_path=str(model))
        (base / "local.json").write_text(json.dumps(config), encoding="utf-8")
        paths = tuple(base / name for name in ("local.json", "inventory.json", "approval.json"))
        for target in ("app.config.runtime_paths", "app.security.runtime_paths"):
            stub = patch(target, return_value=paths)
            stub.start()
            cls.addClassCleanup(stub.stop)
