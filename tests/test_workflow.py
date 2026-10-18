import http.client
import json
import tempfile
import threading
import unittest
from support import SyntheticTestCase
import wave
from pathlib import Path
from unittest.mock import patch

from app.config import ROOT, settings
from app.security import deny_external_network
from app.server import Application, Handler, Server
from app.storage import Store, digest
from launch import preflight


class TestWorkflowPersistence(SyntheticTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="workflow-unit-")
        self.store = Store(Path(self.temp.name))
        source = self.store.inbox / "factice.wav"
        source.write_bytes(b"FACTICE")
        self.identifier = self.store.create(source, "francais")
        self.segments = [{"start":0.0,"end":2.0,"text":"Phrase factice initiale."}]
        self.store.initialize_transcript(self.identifier, self.segments, 3)
        self.raw = self.store.project(self.identifier) / "raw_transcript.json"
        self.raw_hash = digest(self.raw)

    def tearDown(self):
        self.temp.cleanup()

    def test_reopen_preserves_edits_and_raw(self):
        item = self.store.working(self.identifier)
        item["segments"][0]["text"] = "Correction factice : aux bases de données."
        self.store.save(self.identifier, item)
        reopened = Store(self.store.root)
        self.assertEqual(reopened.working(self.identifier)["segments"], item["segments"])
        self.assertEqual(digest(self.raw), self.raw_hash)

    def test_failed_atomic_save_preserves_previous_work_and_raw(self):
        previous = self.store.working(self.identifier)
        item = self.store.working(self.identifier)
        item["segments"][0]["text"] = "Modification factice non enregistrée."
        with patch("app.storage.os.replace", side_effect=OSError("Synthetic disk error")):
            with self.assertRaises(OSError):
                self.store.save(self.identifier, item)
        self.assertEqual(self.store.working(self.identifier), previous)
        self.assertEqual(digest(self.raw), self.raw_hash)

    def test_validation_keeps_raw_and_adds_pdf_duration_and_date(self):
        snapshots = []
        def writer(snapshot, test):
            snapshots.append(snapshot)
            return b"%PDF-1.4\nSYNTHETIC"
        self.store.validate(self.identifier, 0, writer)
        self.assertEqual(snapshots[0]["duration_seconds"], 3)
        self.assertEqual(snapshots[0]["transcription_created_at"], self.store.working(self.identifier)["created_at"])
        self.assertEqual(digest(self.raw), self.raw_hash)
        self.assertEqual(self.store.metadata(self.identifier)["status"], "VALIDATED")


class TestWorkflowHTTP(SyntheticTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="workflow-http-")
        self.app = Application(Path(self.temp.name))
        self.source = self.app.store.inbox / "factice.wav"
        with wave.open(str(self.source), "wb") as wav:
            wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            wav.writeframes(b"\0\0" * 16000)
        self.identifier = self.app.store.create(self.source, "francais")
        self.app.store.initialize_transcript(self.identifier, [{"start":0,"end":1,"text":"Texte factice."}], 1)
        self.project = self.app.store.project(self.identifier)
        (self.project / "work/audio.wav").write_bytes(self.source.read_bytes())
        self.server = Server(("127.0.0.1", 0), Handler)
        self.server.app = self.app
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, action, method="GET", headers=None):
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        client.request(method, f"/api/projects/{self.identifier}/{action}", headers=headers or {})
        response = client.getresponse()
        result = response.status, response.read(), dict(response.getheaders())
        client.close()
        return result

    def test_raw_consultation_is_read_only(self):
        raw = self.project / "raw_transcript.json"
        before = digest(raw)
        status, body, _ = self.request("raw")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["segments"][0]["text"], "Texte factice.")
        status, _, _ = self.request("raw", "POST")
        self.assertEqual(status, 403)
        self.assertEqual(digest(raw), before)

    def test_audio_range_is_exact(self):
        status, body, headers = self.request("media", headers={"Range":"bytes=0-43"})
        self.assertEqual(status, 206)
        self.assertEqual(body, self.source.read_bytes()[:44])
        self.assertEqual(headers["Content-Range"], f"bytes 0-43/{self.source.stat().st_size}")
        self.assertEqual(headers["Content-Type"], "audio/wav")
        self.assertEqual(self.request("media", headers={"Range":"bytes=90000-"})[0], 416)


class TestOfflinePreflight(SyntheticTestCase):
    def test_server_guard_allows_loopback_only(self):
        deny_external_network("socket.connect", (None, ("127.0.0.1", 8765)))
        for event, args in (("socket.connect", (None,("203.0.113.1",443))),
                            ("socket.getaddrinfo", ("huggingface.co",443)),
                            ("socket.sendto", (None,b"test",("203.0.113.1",443)))):
            with self.assertRaises(PermissionError):
                deny_external_network(event, args)

    def test_launcher_absent_model_fails_without_start_or_acquisition(self):
        config = dict(settings(), model_path=str(ROOT / "missing-offline-model"))
        with patch("launch.settings", return_value=config), patch("launch.subprocess.Popen") as process:
            with self.assertRaisesRegex(RuntimeError, "small local"):
                preflight()
            process.assert_not_called()
