import importlib.metadata
import sys
import time
from pathlib import Path

from .config import offline, settings
from .decoder import decode_media
from .diagnostics import failure_record, save_failure
from .security import check_approval, enable_reviewed_imports
from .source import protected_read, stream_digest
from .storage import Store, read_json


def deny_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "socket.sendto"}:
        raise PermissionError("NETWORK_DISABLED")
    if event in {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn"}:
        raise PermissionError("CHILD_PROCESS_DISABLED")


def validate_runtime(config):
    model_path = Path(config["model_path"])
    for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"):
        file = model_path / name
        if not file.is_file() or file.stat().st_size == 0:
            raise FileNotFoundError("MODEL_MISSING")
    if config["device"] != "cpu" or config["compute_type"] != "int8":
        raise ValueError("PROFILE_NOT_QUALIFIED")
    if any(profile.get("task") != "transcribe" for profile in config["profiles"].values()):
        raise ValueError("TRANSLATION_FORBIDDEN")


def bound_final_asr_timestamp(segments, duration):
    """Bound a small ASR tail overrun; storage still validates every timestamp.

    Only the last segment, starting inside the audio, may exceed its duration
    by at most two seconds. Preserve its text and record the original end.
    Larger overruns and segments wholly outside the audio remain errors.
    """
    if segments:
        last = segments[-1]
        if 0 <= last["start"] < duration < last["end"] <= duration + 2.0:
            adjustment = {"policy": "clip_final_end_within_2_seconds",
                "segment_index": len(segments) - 1,
                "original_end": last["end"], "corrected_end": duration}
            return [*segments[:-1], dict(last, end=duration)], adjustment
    return segments, None


def run(root, identifier):
    offline()
    sys.addaudithook(deny_network)
    store = Store(root)
    project = store.project(identifier)
    work = project / "work"
    start = time.monotonic()
    succeeded = False
    technical_stage = "runtime_approval"
    diagnostic = None
    try:
        check_approval()
        technical_stage = "runtime_configuration"
        config = settings()
        validate_runtime(config)
        technical_stage = "reviewed_imports"
        enable_reviewed_imports()
        technical_stage = "source_reference"
        metadata = store.metadata(identifier)
        source = Path(read_json(project / "source_reference.json")["path"])
        if not source.is_file():
            raise FileNotFoundError("SOURCE_MISSING")
        profile = dict(config["profiles"][metadata["profile"]])
        profile.pop("label")
        store.metadata(identifier, status="TRANSCRIBING", stage="Vérification de l’original")
        source_stat = source.stat()
        technical_stage = "source_open"
        with protected_read(source) as stream:
            technical_stage = "source_hash_before"
            before = stream_digest(stream)
            store.metadata(identifier, source_sha256_before=before)
            try:
                technical_stage = "audio_decode"
                store.metadata(identifier, stage="Décodage local PyAV")
                audio, duration = decode_media(stream, work / "audio.wav", metadata["limit_seconds"])
                store.metadata(identifier, stage="Transcription locale", duration_seconds=duration)
                # Offline variables and the network guard are set BEFORE imports.
                technical_stage = "model_import"
                from faster_whisper import WhisperModel
                model_start = time.monotonic()
                technical_stage = "model_load"
                model = WhisperModel(config["model_path"], device=config["device"], compute_type=config["compute_type"],
                                     local_files_only=True)
                technical_stage = "transcription_prepare"
                generated, info = model.transcribe(audio, **profile)
                technical_stage = "transcription_iteration"
                segments = [{"start": float(s.start), "end": float(s.end), "text": s.text.strip()} for s in generated]
                technical_stage = "runtime_metadata"
                actual_device = model.model.device
                actual_compute_type = model.model.compute_type
                versions = {name: importlib.metadata.version(name) for name in ("faster-whisper", "ctranslate2", "av", "numpy")}
                technical_stage = "transcript_storage"
                segments, adjustment = bound_final_asr_timestamp(segments, duration)
                timing_metadata = {"asr_timestamp_adjustment": adjustment} if adjustment else {}
                store.initialize_transcript(identifier, segments, duration, publish=False, model=config["model"], model_revision=config["revision"],
                    model_path=config["model_path"], asr_parameters=profile, versions=versions, device=actual_device,
                    compute_type=actual_compute_type, detected_language=info.language, decoder="PyAV (bundled FFmpeg libraries)",
                    external_ffmpeg_used=False, hf_xet_loaded="hf_xet" in sys.modules,
                    asr_seconds=round(time.monotonic() - model_start, 3), **timing_metadata)
            except BaseException as error:
                # Capture the failing step/time BEFORE the final source rehash.
                diagnostic = failure_record(error, technical_stage, start)
                raise
            finally:
                technical_stage = "source_hash_after"
                try:
                    after = stream_digest(stream)
                    after_stat = source.stat()
                    unchanged = before == after
                    mtime_unchanged = source_stat.st_mtime_ns == after_stat.st_mtime_ns
                    store.metadata(identifier, source_sha256_after=after, source_unchanged=unchanged,
                                   source_mtime_unchanged=mtime_unchanged, os_access_time_update_accepted=True)
                    if not unchanged or not mtime_unchanged:
                        raise RuntimeError("SOURCE_INTEGRITY_FAILED")
                except BaseException as error:
                    integrity_diagnostic = failure_record(error, technical_stage, start)
                    if diagnostic is not None:
                        integrity_diagnostic["preceding_failure"] = diagnostic
                    diagnostic = integrity_diagnostic
                    raise
            technical_stage = "source_close"
        succeeded = True
    except BaseException as error:
        # Exception text from ASR/native libraries can contain private data.
        # The separate diagnostic contains sanitized code coordinates/messages;
        # stdout/stderr and HTTP responses still never expose a raw traceback.
        safe_codes = {"MODEL_MISSING", "SOURCE_MISSING", "PROFILE_NOT_QUALIFIED", "TRANSLATION_FORBIDDEN", "NO_AUDIO_STREAM", "EMPTY_AUDIO",
                      "SOURCE_INTEGRITY_FAILED", "RUNTIME_PATH_CHANGED", "RUNTIME_FILE_CHANGED", "RUNTIME_VERSION_CHANGED", "NETWORK_DISABLED", "CHILD_PROCESS_DISABLED"}
        code = str(error) if str(error) in safe_codes else type(error).__name__
        diagnostic = diagnostic or failure_record(error, technical_stage, start)
        diagnostic_name = save_failure(project, diagnostic)
        store.metadata(identifier, status="ERROR", stage="Traitement arrêté", error_code=code,
                       failure_stage=diagnostic["stage"], diagnostic_file=diagnostic_name)
    finally:
        final = {"status": "DRAFT", "stage": "Prête à corriger"} if succeeded else {}
        store.metadata(identifier, total_seconds=round(time.monotonic() - start, 3), **final)


if __name__ == "__main__":
    run(Path(sys.argv[1]), sys.argv[2])
