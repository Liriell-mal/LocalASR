import hashlib
import http.client
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from support import SyntheticTestCase
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT, check_local_directory, settings
from app.server import Application, Handler, Server
from app.source import protected_read, stream_digest
from app.security import ReviewedImports, ReviewedSourceLoader
from app.storage import Store, digest, read_json, validate_segments, write_bytes
from app.worker import deny_network, validate_runtime


def fake_pdf(snapshot, test):
    return b"%PDF-1.4\nSYNTHETIC_TEST\n" + str(snapshot["version"]).encode("ascii")


class TestStore(SyntheticTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="unit-")
        self.root = Path(self.temporary.name)
        self.store = Store(self.root)
        self.source = self.root / "Vidéo factice avec espaces.wav"
        self.source.write_bytes(b"FACTICE SANS AUDIO PRIVE")
        self.identifier = self.store.create(self.source, "francais", True, 300)
        self.segments = [{"start": 0.0, "end": 1.2, "text": "Phrase factice éàœ."}, {"start": 2.0, "end": 3.0, "text": "Deuxième phrase de test."}]
        self.store.initialize_transcript(self.identifier, self.segments, 4.0)

    def tearDown(self):
        self.temporary.cleanup()

    def test_correction_preserves_raw_and_timestamps(self):
        project = self.store.project(self.identifier)
        before = digest(project / "raw_transcript.json")
        payload = self.store.working(self.identifier)
        payload["segments"][0]["text"] = "Correction factice."
        self.store.save(self.identifier, payload)
        self.assertEqual(self.store.working(self.identifier)["segments"][0]["text"], "Correction factice.")
        self.assertEqual(digest(project / "raw_transcript.json"), before)
        self.assertEqual(self.store.working(self.identifier)["segments"][0]["start"], 0)

    def test_stale_save_is_rejected(self):
        old = self.store.working(self.identifier)
        self.store.save(self.identifier, old)
        with self.assertRaises(ValueError):
            self.store.save(self.identifier, old)

    def test_timestamp_tampering_is_rejected(self):
        item = self.store.working(self.identifier)
        item["segments"][0]["start"] = .5
        with self.assertRaises(ValueError):
            self.store.save(self.identifier, item)

    def test_reset_keeps_immutable_versions(self):
        self.store.validate(self.identifier, 0, fake_pdf)
        item = self.store.working(self.identifier)
        item["segments"][0]["text"] = "Modifié."
        self.store.save(self.identifier, item)
        self.store.reset(self.identifier, 1)
        self.assertEqual(self.store.working(self.identifier)["segments"], self.segments)
        self.assertTrue((self.store.project(self.identifier) / "TEST_validated_v1.json").is_file())

    def test_test_pdf_never_validates_user_text(self):
        first = self.store.validate(self.identifier, 0, fake_pdf, test=False)
        path = self.store.project(self.identifier) / "exports" / first["name"]
        first_hash = digest(path)
        second = self.store.validate(self.identifier, 0, fake_pdf)
        self.assertEqual((first["version"], second["version"]), (1, 2))
        self.assertEqual(first_hash, digest(path))
        self.assertTrue(first["name"].startswith("TEST_"))
        self.assertEqual(self.store.metadata(self.identifier)["status"], "DRAFT")

    def test_pdf_failure_does_not_validate(self):
        def fails(*args):
            raise RuntimeError("synthetic")
        with self.assertRaises(RuntimeError):
            self.store.validate(self.identifier, 0, fails)
        self.assertEqual(self.store.metadata(self.identifier)["status"], "DRAFT")
        self.assertFalse(list(self.store.project(self.identifier).glob("*validated*")))

    def test_human_validation_then_edit_returns_to_draft(self):
        self.store.metadata(self.identifier, test=False)
        self.store.validate(self.identifier, 0, fake_pdf)
        self.assertEqual(self.store.metadata(self.identifier)["status"], "VALIDATED")
        self.store.save(self.identifier, self.store.working(self.identifier))
        self.assertEqual(self.store.metadata(self.identifier)["status"], "DRAFT")

    def test_exports_preserve_existing_files_and_unicode(self):
        for kind in ("txt", "json", "srt"):
            first = self.store.export(self.identifier, kind)
            second = self.store.export(self.identifier, kind)
            self.assertNotEqual(first, second)
            content = (self.store.project(self.identifier) / "exports" / first).read_text("utf-8")
            self.assertIn("éàœ", content)
        self.assertIn("00:00:00,000 --> 00:00:01,200", content)

    def test_raw_creation_cannot_overwrite(self):
        with self.assertRaises(FileExistsError):
            self.store.initialize_transcript(self.identifier, [], 0)

    def test_reject_invalid_time_values(self):
        for value in (-1, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                validate_segments([{"start": value, "end": 2, "text": "Factice"}])

    def test_source_protection_on_owned_fixture(self):
        before = self.source.stat()
        with protected_read(self.source) as stream:
            first = stream_digest(stream)
            self.assertEqual(first, stream_digest(stream))
            self.assertFalse(stream.writable())
        after = self.source.stat()
        self.assertEqual((before.st_mtime_ns, before.st_size), (after.st_mtime_ns, after.st_size))

    def test_path_traversal_and_cloud_rejected(self):
        with self.assertRaises(ValueError):
            self.store.project("../elsewhere")
        with self.assertRaises(ValueError):
            check_local_directory(self.root / "OneDrive" / "project")


class TestRuntime(SyntheticTestCase):
    def test_optional_unreviewed_native_packages_cannot_import(self):
        import importlib.machinery
        from types import SimpleNamespace
        site = Path(settings()["site_packages"])
        finder = ReviewedImports(site, [])
        fake = SimpleNamespace(origin=str(site / "torch" / "__init__.py"))
        with patch.object(importlib.machinery.PathFinder, "find_spec", return_value=fake):
            with self.assertRaises(ModuleNotFoundError):
                finder.find_spec("torch")

    def test_absent_model_no_network_or_import(self):
        config = dict(settings(), model_path=str(ROOT / "absent-model"))
        with self.assertRaisesRegex(FileNotFoundError, "MODEL_MISSING"):
            validate_runtime(config)

    def test_external_ffmpeg_not_required(self):
        config = dict(settings())
        self.assertNotIn("ffmpeg", config)
        validate_runtime(config)

    def test_external_process_and_xet_are_refused(self):
        with self.assertRaises(PermissionError):
            deny_network("subprocess.Popen", ("ffmpeg.exe",))
        finder = ReviewedImports(settings()["site_packages"], [])
        with self.assertRaises(ModuleNotFoundError):
            finder.find_spec("hf_xet")

    def test_translation_is_refused(self):
        config = dict(settings(), profiles={"bad": {"task": "translate"}})
        with self.assertRaisesRegex(ValueError, "TRANSLATION_FORBIDDEN"):
            validate_runtime(config)

    def test_gpu_not_silently_substituted(self):
        config = dict(settings(), device="cuda")
        with self.assertRaisesRegex(ValueError, "PROFILE_NOT_QUALIFIED"):
            validate_runtime(config)

    def test_network_guard_denies_dns_connect_and_udp(self):
        for name in ("socket.connect", "socket.getaddrinfo", "socket.sendto"):
            with self.assertRaises(PermissionError):
                deny_network(name, ())

    def test_automatic_profile_parameters(self):
        profile = settings()["profiles"]["auto"]
        self.assertIsNone(profile["language"])
        self.assertFalse(profile["condition_on_previous_text"])
        self.assertFalse(profile["vad_filter"])
        self.assertEqual(profile["beam_size"], 5)
        self.assertEqual(profile["task"], "transcribe")


class TestHTTP(SyntheticTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="http-")
        self.app = Application(Path(self.temporary.name))
        self.server = Server(("127.0.0.1", 0), Handler)
        self.server.app = self.app
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temporary.cleanup()

    def request(self, method, path, payload=None, headers=None):
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        body = json.dumps(payload).encode() if payload is not None else None
        request_headers = {"Content-Type": "application/json"}
        request_headers.update(headers or {})
        client.request(method, path, body, request_headers)
        response = client.getresponse()
        result = response.status, response.read(), dict(response.getheaders())
        client.close()
        return result

    def test_loopback_and_csp(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        status, body, headers = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("connect-src 'self'", headers["Content-Security-Policy"])
        self.assertNotIn(b"https://", body)

    def test_foreign_host_and_origin_denied(self):
        for headers in ({"Host": "evil.invalid"}, {"Origin": "https://evil.invalid"}, {"Sec-Fetch-Site": "cross-site"}):
            self.assertEqual(self.request("GET", "/api/config", headers=headers)[0], 403)

    def test_mutation_requires_token(self):
        self.assertEqual(self.request("POST", "/api/transcribe", {})[0], 403)

    def test_authorized_upload_preserves_existing_name(self):
        first = self.app.store.inbox / "sample.wav"
        first.write_bytes(b"FIRST")
        headers = {"X-LocalASR-Token": self.app.token}
        status, body, _ = self.request("POST", "/api/upload?name=sample.wav", {"synthetic": True}, headers)
        self.assertEqual(status, 200)
        self.assertNotEqual(json.loads(body)["name"], first.name)
        self.assertEqual(first.read_bytes(), b"FIRST")

    def test_upload_path_escape_denied(self):
        status, _, _ = self.request("POST", "/api/upload?name=../bad.wav", {}, {"X-LocalASR-Token": self.app.token})
        self.assertEqual(status, 400)

    def test_missing_source(self):
        with self.assertRaises(ValueError):
            self.app.start(Path(self.temporary.name) / "absent.mp4", "francais", True, 300)

    def test_unapproved_runtime_rejected_before_worker(self):
        file = self.app.store.inbox / "synthetic.wav"
        file.write_bytes(b"FAKE")
        with patch("app.server.approval_present", return_value=False), patch("app.server.subprocess.Popen") as process:
            with self.assertRaises(PermissionError):
                self.app.start(file, "francais", True, 300)
            process.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
