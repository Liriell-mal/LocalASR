"""Technical exception records. Never serialize values, source lines or locals."""
import sys
import time
import uuid
from pathlib import Path

from .config import ROOT, settings
from .storage import write_json


STAGES = frozenset({
    "runtime_approval", "runtime_configuration", "reviewed_imports",
    "source_reference", "source_open", "source_hash_before", "audio_decode",
    "model_import", "model_load", "transcription_prepare",
    "transcription_iteration", "runtime_metadata", "transcript_storage",
    "source_hash_after", "source_close", "completion", "unknown",
})

# Exact static messages, tied to the function that raises them. In particular,
# never accept a substring/prefix match, repr(error), __notes__ or chained args.
# Unknown library messages may quote recognized text; they must be withheld.
MESSAGES = {
    ("app/storage.py", "validate_segments"): frozenset({
        "Liste de segments incorrecte.", "Horodatages incorrects.",
        "Horodatages hors limites.", "Texte de segment incorrect.",
    }),
    ("app/worker.py", "validate_runtime"): frozenset({
        "MODEL_MISSING", "PROFILE_NOT_QUALIFIED", "TRANSLATION_FORBIDDEN",
    }),
    ("app/worker.py", "run"): frozenset({"SOURCE_MISSING", "SOURCE_INTEGRITY_FAILED"}),
    ("app/worker.py", "deny_network"): frozenset({"NETWORK_DISABLED", "CHILD_PROCESS_DISABLED"}),
    ("app/decoder.py", "decode_media"): frozenset({"NO_AUDIO_STREAM", "EMPTY_AUDIO"}),
    ("app/security.py", "check_approval"): frozenset({
        "RUNTIME_PATH_CHANGED", "RUNTIME_FILE_CHANGED", "RUNTIME_VERSION_CHANGED",
        "Le moteur attend l'autorisation des composants locaux recensés.",
        "L'autorisation des composants locaux doit être vérifiée.",
    }),
    ("app/security.py", "find_spec"): frozenset({
        "Un composant a changé depuis sa vérification.",
        "Component excluded from LocalASR", "Component outside the reviewed inventory",
    }),
    ("app/source.py", "protected_read"): frozenset({"Impossible d'ouvrir la source protégée."}),
}


def technical_frames(error):
    """Only code coordinates under known code roots; no linecache or f_locals."""
    code_roots = [(ROOT / name, name) for name in ("app", "scripts", "tests")]
    code_roots += [(Path(settings()["site_packages"]), "site-packages"),
                   (Path(sys.base_prefix) / "Lib", "stdlib")]
    frames = []
    tb = error.__traceback__
    while tb is not None:
        code = tb.tb_frame.f_code
        file = Path(code.co_filename).absolute()
        label = None
        for root, prefix in code_roots:
            try:
                relative = file.relative_to(root.absolute())
            except ValueError:
                continue
            if file.suffix in {".py", ".pyx"}:
                label = prefix + "/" + relative.as_posix()
                break
        frames.append({"file": label or "<unidentified-code>",
                       "function": code.co_name if label else "<withheld>",
                       "line": tb.tb_lineno})
        tb = tb.tb_next
    return frames


def exception_record(error):
    frames = technical_frames(error)
    origin = frames[-1] if frames else {}
    allowed = MESSAGES.get((origin.get("file"), origin.get("function")), ())
    # Use the single plain-string argument directly, not a custom __str__.
    exact = (len(error.args) == 1 and type(error.args[0]) is str
             and error.args[0] in allowed)
    return {
        "exception_class": type(error).__name__,
        "message": error.args[0] if exact else "MESSAGE_WITHHELD_FOR_CONFIDENTIALITY",
        "message_policy": "exact_static_allowlist" if exact else "withheld",
        "traceback": frames,
    }


def failure_record(error, stage, started_at):
    result = {"schema_version": 1, "stage": stage if stage in STAGES else "unknown",
              "elapsed_seconds": round(time.monotonic() - started_at, 3),
              **exception_record(error)}
    # Preserve useful chained stacks, under the very same message policy.
    causes, seen = [], {id(error)}
    current = error
    while len(causes) < 8:
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        causes.append(exception_record(current))
    if causes:
        result["causes"] = causes
    return result


def save_failure(project, record):
    name = "diagnostic-" + uuid.uuid4().hex + ".json"
    write_json(project / name, record, exclusive=True)
    return name
