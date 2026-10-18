import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import ROOT, runtime_mode, runtime_paths
from app.security import approval_present, check_approval, enable_reviewed_imports
from launch import health
from app.independence import path_guard


class TestRuntimeSelection(unittest.TestCase):
    def test_default_paths_use_qualified_independent_runtime(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(runtime_mode(), "independent")
            self.assertTrue(all(p.is_relative_to(ROOT / "runtime/independent") for p in runtime_paths()))

    def test_other_runtime_is_rejected(self):
        with patch.dict(os.environ, {"LOCALASR_RUNTIME":"other"}, clear=True):
            with self.assertRaisesRegex(ValueError, "RUNTIME_SELECTION_INVALID"):
                runtime_paths()

    def test_independent_paths_never_fallback(self):
        with patch.dict(os.environ, {"LOCALASR_RUNTIME":"independent"}):
            self.assertTrue(all(p.is_relative_to(ROOT / "runtime/independent") for p in runtime_paths()))
        with patch.dict(os.environ, {"LOCALASR_RUNTIME":"other"}):
            with self.assertRaisesRegex(ValueError, "RUNTIME_SELECTION_INVALID"):
                runtime_paths()

    def test_unapproved_candidate_refused_before_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "inventory.json").write_text('{"files":[]}', encoding="utf-8")
            (base / "approval.json").write_text('{"approved":false}', encoding="utf-8")
            paths = (base / "local.json", base / "inventory.json", base / "approval.json")
            before = list(sys.path)
            before_finders = list(sys.meta_path)
            with patch("app.security.runtime_paths", return_value=paths):
                self.assertFalse(approval_present())
                with self.assertRaises(PermissionError):
                    check_approval()
                with self.assertRaises(PermissionError):
                    enable_reviewed_imports()
            self.assertEqual(sys.path, before)
            self.assertEqual(sys.meta_path, before_finders)

    def test_launcher_never_reuses_server_from_other_runtime(self):
        data = ROOT / "test-runs"
        with patch.dict(os.environ, {"LOCALASR_RUNTIME":"independent"}), patch("launch.local_request", return_value={
            "application":"LocalASR", "data_dir":str(data), "runtime":"other"}):
            self.assertIsNone(health("http://127.0.0.1:8765", data))

    def test_independence_guard_denies_old_paths_without_changing_them(self):
        failures = []
        folder = ROOT / "synthetic-forbidden-root"
        guard = path_guard(folder, failures)
        for event in ("open", "os.scandir", "os.add_dll_directory", "ctypes.dlopen"):
            with self.assertRaisesRegex(PermissionError, "FORBIDDEN_ROOT_ACCESS"):
                guard(event, (str(folder / "synthetic-never-opened.py"),))
        guard("open", (str(ROOT / "app/config.py"),))
        self.assertEqual(len(failures), 4)
