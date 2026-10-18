import contextlib
import io
import json
import sys
import tempfile
import time
import unittest
from support import SyntheticTestCase
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import worker
from app.config import ROOT, settings
from app.diagnostics import failure_record
from app.storage import Store, digest, read_json, validate_segments


PRIVATE = "SENTINEL_PRIVATE_TRANSCRIPT_AND_PROMPT_83c420"


class TestDiagnostics(SyntheticTestCase):
    def test_exact_static_message_and_frames_without_locals_or_source(self):
        try:
            # Contents are deliberately private; only the static error is safe.
            validate_segments([{"start": 0, "end": 5, "text": PRIVATE}], 4)
        except ValueError as error:
            record = failure_record(error, "transcript_storage", time.monotonic())
        self.assertEqual(record["message"], "Horodatages hors limites.")
        self.assertEqual(record["exception_class"], "ValueError")
        self.assertEqual(record["message_policy"], "exact_static_allowlist")
        self.assertEqual(record["traceback"][-1]["file"], "app/storage.py")
        self.assertEqual(record["traceback"][-1]["function"], "validate_segments")
        self.assertTrue(all(set(frame) == {"file", "function", "line"} for frame in record["traceback"]))
        self.assertNotIn(PRIVATE, json.dumps(record))

    def test_unknown_message_chained_args_and_notes_are_withheld(self):
        try:
            try:
                raise ValueError(PRIVATE)
            except ValueError as cause:
                error = RuntimeError("Horodatages hors limites. " + PRIVATE)
                error.add_note(PRIVATE)
                raise error from cause
        except RuntimeError as error:
            record = failure_record(error, "transcription_iteration", time.monotonic())
        self.assertEqual(record["message_policy"], "withheld")
        self.assertEqual(record["causes"][0]["exception_class"], "ValueError")
        self.assertNotIn(PRIVATE, json.dumps(record))

    def test_message_spoofed_outside_origin_is_not_accepted(self):
        try:
            raise ValueError("Horodatages hors limites.")
        except ValueError as error:
            record = failure_record(error, "transcription_iteration", time.monotonic())
        self.assertEqual(record["message_policy"], "withheld")

    def test_exception_string_method_is_never_used(self):
        class DangerousError(Exception):
            def __str__(self):
                raise AssertionError("Diagnostic must not call __str__")
        try:
            raise DangerousError(PRIVATE)
        except DangerousError as error:
            record = failure_record(error, "model_load", time.monotonic())
        self.assertNotIn(PRIVATE, json.dumps(record))

    def test_dynamic_code_filename_is_not_copied(self):
        try:
            exec(compile("raise ValueError('hidden')", PRIVATE, "exec"), {})
        except ValueError as error:
            record = failure_record(error, PRIVATE, time.monotonic())
        self.assertNotIn(PRIVATE, json.dumps(record))
        self.assertEqual(record["stage"], "unknown")
        self.assertEqual(record["traceback"][-1]["file"], "<unidentified-code>")


class TestInstrumentedWorker(SyntheticTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="diagnostic-unit-")
        self.store = Store(Path(self.temporary.name))
        self.source = self.store.inbox / "fictitious.wav"
        self.source.write_bytes(b"SYNTHETIC SOURCE")
        self.identifier = self.store.create(self.source, "francais", False, None)

    def tearDown(self):
        self.temporary.cleanup()

    def exercise(self, failure=None):
        model_calls = {}

        def maybe_fail(stage):
            if failure == stage:
                raise ValueError(PRIVATE)

        class FakeModel:
            def __init__(self, path, **kwargs):
                maybe_fail("model_load")
                model_calls["load"] = dict(kwargs, path=path)
                self.model = SimpleNamespace(device="cpu", compute_type="int8_float32")

            def transcribe(self, audio, **profile):
                maybe_fail("transcription_prepare")
                model_calls["profile"] = profile

                def generated():
                    end = 7.0 if failure == "transcript_storage" else (4.5 if failure == "tail_timestamp" else 1.0)
                    yield SimpleNamespace(start=0.0, end=end, text=PRIVATE)
                    maybe_fail("transcription_iteration")

                return generated(), SimpleNamespace(language="fr")

        def decode(source, destination, limit):
            maybe_fail("audio_decode")
            destination.write_bytes(b"SYNTHETIC AUDIO PLACEHOLDER")
            return object(), 4.0

        output = io.StringIO()
        with contextlib.ExitStack() as stack:
            for name in ("check_approval", "validate_runtime", "enable_reviewed_imports"):
                stack.enter_context(patch.object(worker, name))
            stack.enter_context(patch.object(worker.sys, "addaudithook"))
            stack.enter_context(patch.object(worker, "decode_media", side_effect=decode))
            stack.enter_context(patch.object(worker.importlib.metadata, "version", return_value="synthetic-version"))
            stack.enter_context(patch.dict(sys.modules, {"faster_whisper": SimpleNamespace(WhisperModel=FakeModel)}))
            stack.enter_context(contextlib.redirect_stdout(output))
            stack.enter_context(contextlib.redirect_stderr(output))
            worker.run(self.store.root, self.identifier)
        self.assertEqual(output.getvalue(), "")
        return self.store.metadata(self.identifier), model_calls

    def test_success_preserves_normal_outputs_and_profile(self):
        before = digest(self.source)
        metadata, calls = self.exercise()
        project = self.store.project(self.identifier)
        self.assertEqual(metadata["status"], "DRAFT")
        self.assertEqual(metadata["segment_count"], 1)
        self.assertTrue(metadata["source_unchanged"])
        self.assertEqual(before, digest(self.source))
        self.assertEqual(calls["profile"], {k:v for k,v in settings()["profiles"]["francais"].items() if k != "label"})
        self.assertEqual(calls["load"]["compute_type"], "int8")
        self.assertTrue(calls["load"]["local_files_only"])
        self.assertEqual(read_json(project / "raw_transcript.json")["segments"], self.store.working(self.identifier)["segments"])
        self.assertTrue((project / "raw_transcript.srt").is_file())
        self.assertFalse(list(project.glob("diagnostic-*.json")))
        self.assertNotIn("diagnostic_file", metadata)

    def assert_failure(self, stage, expected_message="MESSAGE_WITHHELD_FOR_CONFIDENTIALITY"):
        metadata, _ = self.exercise(stage)
        project = self.store.project(self.identifier)
        self.assertEqual(metadata["status"], "ERROR")
        self.assertEqual(metadata["error_code"], "ValueError")
        self.assertEqual(metadata["failure_stage"], stage)
        self.assertTrue(metadata["source_unchanged"])
        diagnostic = read_json(project / metadata["diagnostic_file"])
        self.assertEqual(diagnostic["stage"], stage)
        self.assertEqual(diagnostic["message"], expected_message)
        self.assertGreaterEqual(diagnostic["elapsed_seconds"], 0)
        self.assertLessEqual(diagnostic["elapsed_seconds"], metadata["total_seconds"])
        self.assertNotIn(PRIVATE, json.dumps(diagnostic))
        self.assertNotIn(PRIVATE, json.dumps(metadata))
        self.assertFalse((project / "raw_transcript.json").exists())
        self.assertEqual(len(list(project.glob("diagnostic-*.json"))), 1)
        return diagnostic

    def test_storage_exception_has_exact_message_and_caller_stack(self):
        diagnostic = self.assert_failure("transcript_storage", "Horodatages hors limites.")
        self.assertEqual([f["function"] for f in diagnostic["traceback"]], ["run", "initialize_transcript", "validate_segments"])

    def test_small_asr_tail_overrun_is_bounded_and_recorded(self):
        metadata, _ = self.exercise("tail_timestamp")
        self.assertEqual(metadata["status"], "DRAFT")
        self.assertTrue(metadata["source_unchanged"])
        self.assertEqual(metadata["asr_timestamp_adjustment"], {
            "policy": "clip_final_end_within_2_seconds", "segment_index": 0,
            "original_end": 4.5, "corrected_end": 4.0})
        segments = read_json(self.store.project(self.identifier) / "raw_transcript.json")["segments"]
        self.assertEqual(segments, [{"start": 0.0, "end": 4.0, "text": PRIVATE}])
        self.assertEqual(self.store.working(self.identifier)["segments"], segments)

    def test_decode_error_preserves_stage_before_final_source_hash(self):
        self.assert_failure("audio_decode")

    def test_model_loading_error(self):
        self.assert_failure("model_load")

    def test_feature_preparation_error(self):
        self.assert_failure("transcription_prepare")

    def test_lazy_generator_error_does_not_leak_partial_segments(self):
        self.assert_failure("transcription_iteration")
