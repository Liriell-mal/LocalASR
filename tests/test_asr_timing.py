import copy
import tempfile
import unittest
from pathlib import Path

from support import SyntheticTestCase
from app.storage import Store, digest, read_json, validate_segments
from app.worker import bound_final_asr_timestamp


class TestASRTiming(unittest.TestCase):
    def test_final_overrun_preserves_all_text_and_original_input(self):
        segments = [{"start": 7.0, "end": 8.5, "text": "Première phrase factice."},
                    {"start": 9.0, "end": 11.5, "text": "Fin factice.", "extra": {"synthetic": True}}]
        before = copy.deepcopy(segments)
        result, adjustment = bound_final_asr_timestamp(segments, 10.25)
        validate_segments(result, 10.25)
        self.assertEqual(segments, before)
        self.assertEqual(result, [segments[0], dict(segments[1], end=10.25)])
        self.assertEqual(adjustment["original_end"], 11.5)
        self.assertEqual(adjustment["corrected_end"], 10.25)
        self.assertEqual(adjustment["segment_index"], 1)

    def test_valid_and_empty_results_are_unchanged(self):
        for segments in ([], [{"start": 0.0, "end": 10.0, "text": "Factice"}]):
            result, adjustment = bound_final_asr_timestamp(segments, 10.0)
            self.assertEqual(result, segments)
            self.assertIsNone(adjustment)

    def test_two_second_limit_is_enforced(self):
        for end, accepted in ((12.0, True), (12.001, False), (1000.0, False)):
            with self.subTest(end=end):
                result, adjustment = bound_final_asr_timestamp(
                    [{"start": 9.0, "end": end, "text": "Factice"}], 10.0)
                if accepted:
                    validate_segments(result, 10.0)
                    self.assertEqual(result[0]["end"], 10.0)
                else:
                    self.assertIsNone(adjustment)
                    with self.assertRaises(ValueError):
                        validate_segments(result, 10.0)

    def test_other_timestamp_anomalies_remain_errors(self):
        cases = [
            [{"start": 10.0, "end": 11.0, "text": "Entirely after audio"}],
            [{"start": -1.0, "end": 11.0, "text": "Negative start"}],
            [{"start": 9.0, "end": 8.0, "text": "Inverted"}],
            [{"start": 1.0, "end": float("inf"), "text": "Infinite"}],
            [{"start": float("nan"), "end": 11.0, "text": "Not a number"}],
            [{"start": 8.0, "end": 9.0, "text": "First"},
             {"start": 7.0, "end": 11.0, "text": "Backwards"}],
            [{"start": 8.0, "end": 11.0, "text": "Non-final overrun"},
             {"start": 9.0, "end": 11.5, "text": "Final"}],
        ]
        for segments in cases:
            with self.subTest(segments=segments):
                result, _ = bound_final_asr_timestamp(segments, 10.0)
                with self.assertRaises(ValueError):
                    validate_segments(result, 10.0)

    def test_small_non_terminal_overrun_is_rejected(self):
        segments = [{"start": 8.0, "end": 10.05, "text": "Interior"},
                    {"start": 9.0, "end": 11.5, "text": "Final"}]
        result, _ = bound_final_asr_timestamp(segments, 10.0)
        with self.assertRaises(ValueError):
            validate_segments(result, 10.0)

    def test_small_segment_wholly_after_audio_is_rejected(self):
        result, adjustment = bound_final_asr_timestamp(
            [{"start": 10.01, "end": 10.05, "text": "Outside"}], 10.0)
        self.assertIsNone(adjustment)
        with self.assertRaises(ValueError):
            validate_segments(result, 10.0)


class TestTimingExports(SyntheticTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="timing-export-")
        self.addCleanup(temporary.cleanup)
        self.store = Store(Path(temporary.name))
        source = self.store.inbox / "synthetic.wav"
        source.write_bytes(b"SYNTHETIC SOURCE")
        self.identifier = self.store.create(source, "francais", True, None)
        self.original = [{"start": 9.0, "end": 11.5, "text": "Phrase factice complète."}]
        self.segments, adjustment = bound_final_asr_timestamp(self.original, 10.25)
        self.store.initialize_transcript(self.identifier, self.segments, 10.25,
                                         asr_timestamp_adjustment=adjustment)
        self.project = self.store.project(self.identifier)

    def test_srt_json_txt_use_normalized_bounds_and_complete_text(self):
        for kind in ("srt", "json", "txt"):
            name = self.store.export(self.identifier, kind)
            path = self.project / "exports" / name
            text = path.read_text("utf-8")
            self.assertIn(self.original[0]["text"], text)
            if kind == "srt":
                self.assertIn("00:00:09,000 --> 00:00:10,250", text)
                self.assertNotIn("00:00:11,500", text)
            if kind == "json":
                self.assertEqual(read_json(path)["segments"], self.segments)
        self.assertIn("00:00:10,250", (self.project / "raw_transcript.srt").read_text("utf-8"))

    def test_pdf_snapshot_and_edits_keep_raw_and_original_timing_evidence(self):
        raw_hash = digest(self.project / "raw_transcript.json")
        edited = self.store.working(self.identifier)
        edited["segments"][0]["text"] = "Correction factice complète."
        self.store.save(self.identifier, edited)
        captured = []
        def pdf(snapshot, test):
            captured.append(copy.deepcopy(snapshot))
            return b"%PDF-1.4 SYNTHETIC TEST"
        result = self.store.validate(self.identifier, 1, pdf)
        self.assertTrue(result["test"])
        self.assertEqual(captured[0]["duration_seconds"], 10.25)
        self.assertEqual(captured[0]["segments"], [dict(self.segments[0], text=edited["segments"][0]["text"])])
        self.assertEqual(digest(self.project / "raw_transcript.json"), raw_hash)
        self.assertEqual(read_json(self.project / "raw_transcript.json")["segments"], self.segments)
        self.assertEqual(self.store.metadata(self.identifier)["asr_timestamp_adjustment"]["original_end"], 11.5)
