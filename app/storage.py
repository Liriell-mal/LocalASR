import hashlib
import json
import math
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import check_local_directory


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    result = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value, *, exclusive=False):
    write_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"), exclusive=exclusive)


def write_bytes(path, value, *, exclusive=False):
    path = Path(path)
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            # Hard-link publication is atomic and fails if the destination exists.
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def timestamp(seconds, srt=False):
    milliseconds = round(seconds * 1000)
    hours, rest = divmod(milliseconds, 3600000)
    minutes, rest = divmod(rest, 60000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}{',' if srt else '.'}{ms:03}"


def as_srt(segments):
    return "\n\n".join(f"{i}\n{timestamp(s['start'], True)} --> {timestamp(s['end'], True)}\n{s['text']}" for i, s in enumerate(segments, 1)) + "\n"


def validate_segments(segments, duration=None):
    if not isinstance(segments, list) or len(segments) > 100000:
        raise ValueError("Liste de segments incorrecte.")
    previous = -1.0
    for segment in segments:
        start, end = segment.get("start"), segment.get("end")
        if not all(isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v) for v in (start, end)):
            raise ValueError("Horodatages incorrects.")
        if not 0 <= start <= end or start < previous or (duration is not None and end > duration):
            raise ValueError("Horodatages hors limites.")
        if not isinstance(segment.get("text"), str) or len(segment["text"]) > 100000:
            raise ValueError("Texte de segment incorrect.")
        previous = start


class Store:
    def __init__(self, root):
        self.root = check_local_directory(root)
        self.projects = self.root / "projects"
        self.inbox = self.root / "inbox"
        self.projects.mkdir(parents=True, exist_ok=True)
        self.inbox.mkdir(exist_ok=True)
        self.lock = threading.RLock()

    def project(self, identifier):
        if not re.fullmatch(r"[0-9a-f]{32}", identifier):
            raise ValueError("Identifiant incorrect.")
        path = self.projects / identifier
        check_local_directory(path)
        if not path.is_dir():
            raise FileNotFoundError("Projet absent.")
        return path

    def create(self, source, profile, test=False, limit=None):
        with self.lock:
            identifier = uuid.uuid4().hex
            project = self.projects / identifier
            project.mkdir()
            (project / "work").mkdir()
            (project / "exports").mkdir()
            write_json(project / "source_reference.json", {"path": str(source), "name": source.name}, exclusive=True)
            write_json(project / "metadata.json", {"id": identifier, "source_name": source.name,
                "created_at": now(), "profile": profile, "test": test, "limit_seconds": limit,
                "status": "QUEUED", "stage": "En attente", "version": 0}, exclusive=True)
            return identifier

    def metadata(self, identifier, **updates):
        with self.lock:
            path = self.project(identifier) / "metadata.json"
            data = read_json(path)
            if updates:
                data.update(updates)
                write_json(path, data)
            return data

    def list_projects(self):
        result = []
        for path in self.projects.iterdir():
            if re.fullmatch(r"[0-9a-f]{32}", path.name) and not path.is_symlink() and not path.is_junction():
                try:
                    result.append(self.metadata(path.name))
                except (OSError, ValueError):
                    pass
        return sorted(result, key=lambda item: item["created_at"], reverse=True)

    def initialize_transcript(self, identifier, segments, duration, publish=True, **technical):
        validate_segments(segments, duration)
        with self.lock:
            project = self.project(identifier)
            raw = {"segments": segments, "created_at": now()}
            write_json(project / "raw_transcript.json", raw, exclusive=True)
            write_bytes(project / "raw_transcript.srt", as_srt(segments).encode("utf-8"), exclusive=True)
            write_json(project / "working_transcript.json", dict(raw, revision=0, title="Transcription", participants=""), exclusive=True)
            self.metadata(identifier, status="DRAFT" if publish else "TRANSCRIBING", stage="Prête à corriger" if publish else "Vérification finale de l’original", duration_seconds=duration,
                          segment_count=len(segments), raw_sha256=digest(project / "raw_transcript.json"), **technical)

    def working(self, identifier):
        with self.lock:
            return read_json(self.project(identifier) / "working_transcript.json")

    def save(self, identifier, payload):
        with self.lock:
            project = self.project(identifier)
            current = self.working(identifier)
            if payload.get("revision") != current["revision"]:
                raise ValueError("Cette version a changé. Rechargez le projet avant de sauvegarder.")
            segments = payload.get("segments")
            validate_segments(segments, self.metadata(identifier)["duration_seconds"])
            if [(s["start"], s["end"]) for s in segments] != [(s["start"], s["end"]) for s in current["segments"]]:
                raise ValueError("La correction doit conserver les horodatages.")
            title, participants = payload.get("title", "Transcription"), payload.get("participants", "")
            if not isinstance(title, str) or not isinstance(participants, str) or len(title) > 500 or len(participants) > 4000:
                raise ValueError("Titre ou participants incorrects.")
            updated = dict(current, segments=segments, title=title, participants=participants,
                           revision=current["revision"] + 1, saved_at=now())
            write_json(project / "working_transcript.json", updated)
            self.metadata(identifier, status="DRAFT", stage="Corrections enregistrées")
            return {"revision": updated["revision"], "saved_at": updated["saved_at"]}

    def reset(self, identifier, revision):
        with self.lock:
            current = self.working(identifier)
            raw = read_json(self.project(identifier) / "raw_transcript.json")
            return self.save(identifier, dict(current, revision=revision, segments=raw["segments"]))

    def export(self, identifier, kind):
        with self.lock:
            current = self.working(identifier)
            if kind == "json":
                data = json.dumps(current, ensure_ascii=False, indent=2).encode("utf-8")
            elif kind == "srt":
                data = as_srt(current["segments"]).encode("utf-8")
            elif kind == "txt":
                data = (current["title"] + "\n\n" + "\n".join(f"[{timestamp(s['start'])}] {s['text']}" for s in current["segments"])).encode("utf-8")
            else:
                raise ValueError("Format inconnu.")
            name = f"transcription_{uuid.uuid4().hex[:12]}.{kind}"
            write_bytes(self.project(identifier) / "exports" / name, data, exclusive=True)
            return name

    def validate(self, identifier, revision, pdf_writer, test=False):
        with self.lock:
            project = self.project(identifier)
            metadata = self.metadata(identifier)
            current = self.working(identifier)
            if current["revision"] != revision:
                raise ValueError("Sauvegardez les dernières corrections avant la validation.")
            test = bool(test or metadata["test"])
            prefix = "TEST_" if test else ""
            version = 1
            while (project / f"{prefix}validated_v{version}.json").exists() or (project / "exports" / f"{prefix}transcription_v{version}.pdf").exists():
                version += 1
            snapshot = dict(current, version=version, validation="TEST_NON_VALIDE" if test else "VALIDATED",
                            exported_at=now(), source_name=metadata["source_name"],
                            duration_seconds=metadata.get("duration_seconds"),
                            transcription_created_at=current.get("created_at"))
            # Generate first; a failed PDF never marks the draft as validated.
            pdf = pdf_writer(snapshot, test)
            snapshot_name = f"{prefix}validated_v{version}.json"
            pdf_name = f"{prefix}transcription_v{version}.pdf"
            write_json(project / snapshot_name, snapshot, exclusive=True)
            write_bytes(project / "exports" / pdf_name, pdf, exclusive=True)
            self.metadata(identifier, status="DRAFT" if test else "VALIDATED", version=version,
                          stage="PDF TEST créé — non validé" if test else "Version validée", last_pdf=pdf_name)
            return {"name": pdf_name, "version": version, "test": test}
