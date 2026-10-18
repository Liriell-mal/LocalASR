import argparse
import hmac
import json
import mimetypes
import os
import re
import secrets
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .config import ROOT, MEDIA_EXTENSIONS, check_local_directory, offline, runtime_mode, settings
from .pdf import make_pdf
from .security import approval_present, deny_external_network
from .storage import Store, read_json, write_json


class Application:
    def __init__(self, data):
        self.store = Store(data)
        self.token = secrets.token_urlsafe(32)
        self.guard = threading.Lock()
        self.process = None
        # Only the fresh server's workers can be active; mark interrupted jobs.
        for item in self.store.list_projects():
            if item["status"] in ("QUEUED", "TRANSCRIBING"):
                self.store.metadata(item["id"], status="ERROR", stage="Traitement interrompu", error_code="INTERRUPTED")

    def start(self, source, profile, test, limit):
        if profile not in settings()["profiles"]:
            raise ValueError("Profil inconnu.")
        if not isinstance(test, bool) or (limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 300)):
            raise ValueError("Durée de test incorrecte.")
        if test:
            limit = 300 if limit is None else limit
        source = Path(source).absolute()
        if not source.is_file() or source.suffix.lower() not in MEDIA_EXTENSIONS:
            raise ValueError("Choisissez un média local pris en charge.")
        check_local_directory(source.parent)
        if source.is_symlink():
            raise ValueError("Les liens de fichiers ne sont pas acceptés.")
        if not approval_present():
            raise PermissionError("Le moteur attend l'autorisation des composants locaux recensés.")
        with self.guard:
            if self.process is not None and self.process.poll() is None:
                raise ValueError("Une transcription est déjà en cours.")
            identifier = self.store.create(source, profile, test, limit)
            try:
                self.process = subprocess.Popen([settings()["python"], "-I", "-B", "-S", str(ROOT / "run.py"), "worker", str(self.store.root), identifier],
                    cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except OSError:
                self.store.metadata(identifier, status="ERROR", stage="Démarrage impossible", error_code="WORKER_START_FAILED")
                raise ValueError("Impossible de démarrer le moteur local.") from None
            return {"id": identifier}


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass  # Never dump request data or a traceback containing private text.


class Handler(BaseHTTPRequestHandler):
    server_version = "LocalASR"

    def log_message(self, *args):
        pass

    @property
    def app(self):
        return self.server.app

    def respond(self, value, status=200, content_type="application/json; charset=utf-8", extra=None):
        data = json.dumps(value, ensure_ascii=False).encode("utf-8") if content_type.startswith("application/json") else value
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; media-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        for key, val in (extra or {}).items():
            self.send_header(key, val)
        self.end_headers()
        self.wfile.write(data)

    def secure(self, mutation=False):
        expected = f"127.0.0.1:{self.server.server_port}"
        if self.client_address[0] != "127.0.0.1" or self.headers.get("Host") != expected:
            raise PermissionError("Accès local requis.")
        origin = self.headers.get("Origin")
        if origin is not None and origin != "http://" + expected:
            raise PermissionError("Origine refusée.")
        if self.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
            raise PermissionError("Origine refusée.")
        if mutation and not hmac.compare_digest(self.headers.get("X-LocalASR-Token", ""), self.app.token):
            raise PermissionError("Rechargez l’interface locale.")

    def body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 32 * 1024 * 1024 or self.headers.get_content_type() != "application/json":
            raise ValueError("Requête incorrecte.")
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        self.dispatch(False)

    def do_POST(self):
        self.dispatch(True)

    def dispatch(self, mutation):
        try:
            self.secure(mutation)
            parsed = urlsplit(self.path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query)
            if mutation:
                self.post(path, query)
            else:
                self.get(path)
        except PermissionError as error:
            self.respond({"error": str(error)}, 403)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            # Input exceptions may quote private payloads. Do not echo them.
            self.respond({"error": "Action impossible. Vérifiez la sélection ou rechargez le projet après sauvegarde."}, 400)
        except FileNotFoundError:
            self.respond({"error": "Fichier local absent."}, 404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception:
            self.respond({"error": "L’opération locale a échoué. Les versions antérieures sont conservées."}, 500)

    def get(self, path):
        if path == "/api/health":
            return self.respond({"application": "LocalASR", "data_dir": str(self.app.store.root),
                "runtime": runtime_mode(),
                "busy": self.app.process is not None and self.app.process.poll() is None})
        if path == "/api/config":
            profiles = settings()["profiles"]
            return self.respond({"token": self.app.token, "profiles": {k: profiles[k] for k in ("francais", "anglais", "auto") if k in profiles}, "ready": approval_present(),
                                 "inbox": str(self.app.store.inbox)})
        if path == "/api/projects":
            return self.respond(self.app.store.list_projects())
        if path == "/api/inbox":
            return self.respond([p.name for p in self.app.store.inbox.iterdir() if p.is_file() and not p.is_symlink() and p.suffix.lower() in MEDIA_EXTENSIONS])
        match = re.fullmatch(r"/api/projects/([a-f0-9]{32})(?:/(working|raw|media|files/[^/]+))?", path)
        if match:
            identifier, action = match.groups()
            project = self.app.store.project(identifier)
            if action is None:
                return self.respond(self.app.store.metadata(identifier))
            if action == "working":
                return self.respond(self.app.store.working(identifier))
            if action == "raw":
                return self.respond(read_json(project / "raw_transcript.json"))
            if action == "media":
                return self.send_file(project / "work" / "audio.wav", "audio/wav", ranges=True)
            if action.startswith("files/"):
                name = action.split("/")[1]
                if not re.fullmatch(r"(?:TEST_)?transcription_(?:v[0-9]+|[a-f0-9]{12})\.(?:pdf|txt|srt|json)", name):
                    raise ValueError("Nom incorrect.")
                return self.send_file(project / "exports" / name, mimetypes.guess_type(name)[0] or "application/octet-stream", download=name)
        assets = {"/": ROOT / "templates" / "index.html", "/static/app.js": ROOT / "static" / "app.js", "/static/style.css": ROOT / "static" / "style.css"}
        if path in assets:
            item = assets[path]
            return self.respond(item.read_bytes(), content_type=(mimetypes.guess_type(item.name)[0] or "text/plain") + "; charset=utf-8")
        self.respond({"error": "Introuvable."}, 404)

    def send_file(self, path, content_type, download=None, ranges=False):
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        if ranges and self.headers.get("Range"):
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers["Range"])
            if not match:
                return self.respond({"error": "Plage incorrecte."}, 416)
            start, last = match.groups()
            start, end = int(start), min(int(last) if last else end, end)
            if not 0 <= start <= end < size:
                return self.respond({"error": "Plage incorrecte."}, 416)
            status = 206
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        if ranges:
            self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        self.end_headers()
        with path.open("rb") as stream:
            stream.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def post(self, path, query):
        if path == "/api/shutdown":
            if self.app.process is not None and self.app.process.poll() is None:
                raise ValueError("Une transcription est en cours.")
            self.respond({"stopping": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if path == "/api/upload":
            name = query.get("name", [""])[0]
            if Path(name).name != name or Path(name).suffix.lower() not in MEDIA_EXTENSIONS:
                raise ValueError("Fichier incorrect.")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 50 * 1024 ** 3:
                raise ValueError("Taille incorrecte.")
            name = uuid.uuid4().hex[:10] + "_" + name
            destination = self.app.store.inbox / name
            partial = destination.with_suffix(destination.suffix + ".partial")
            try:
                with partial.open("xb") as stream:
                    remaining = length
                    while remaining:
                        chunk = self.rfile.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ValueError("Copie interrompue.")
                        stream.write(chunk)
                        remaining -= len(chunk)
                os.rename(partial, destination)
            finally:
                partial.unlink(missing_ok=True)
            return self.respond({"name": name})
        payload = self.body()
        if path == "/api/transcribe":
            if payload.get("reference"):
                source = Path(payload["reference"])
            else:
                name = payload["inbox_name"]
                if Path(name).name != name:
                    raise ValueError("Nom incorrect.")
                source = self.app.store.inbox / name
            return self.respond(self.app.start(source, payload.get("profile", "francais"), payload.get("test", False), payload.get("limit_seconds")), 202)
        match = re.fullmatch(r"/api/projects/([a-f0-9]{32})/(save|reset|validate|export)", path)
        if not match:
            return self.respond({"error": "Introuvable."}, 404)
        identifier, action = match.groups()
        if action == "save":
            return self.respond(self.app.store.save(identifier, payload))
        if action == "reset":
            return self.respond(self.app.store.reset(identifier, payload["revision"]))
        if action == "validate":
            return self.respond(self.app.store.validate(identifier, payload["revision"], make_pdf, payload.get("test", False)))
        return self.respond({"name": self.app.store.export(identifier, payload["format"])})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--ready-file", type=Path)
    args = parser.parse_args()
    offline()
    app = Application(args.data_dir)
    server = Server(("127.0.0.1", args.port), Handler)
    server.app = app
    sys.addaudithook(deny_external_network)
    if args.ready_file:
        write_json(args.ready_file, {"pid": os.getpid(), "url": f"http://127.0.0.1:{server.server_port}", "data": str(app.store.root)}, exclusive=True)
    print(f"LocalASR : http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
