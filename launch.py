"""Local Windows launcher. No acquisition, installation or policy changes."""
import argparse
import hashlib
import http.client
import json
import os
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from app.config import check_local_directory, offline, runtime_mode, settings
from app.security import check_approval
from app.storage import read_json, write_json
from app.worker import validate_runtime


def local_request(url, path, payload=None, token=None):
    address = urlsplit(url)
    if address.scheme != "http" or address.hostname != "127.0.0.1":
        raise ValueError("Adresse locale incorrecte.")
    connection = http.client.HTTPConnection("127.0.0.1", address.port, timeout=2)
    try:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-LocalASR-Token"] = token
        connection.request("POST" if payload is not None else "GET", path,
                           json.dumps(payload) if payload is not None else None, headers)
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("Le serveur local n'accepte pas cette opération.")
        return json.loads(response.read())
    finally:
        connection.close()


def health(url, data):
    try:
        result = local_request(url, "/api/health")
        return result if (result.get("application") == "LocalASR" and
            result.get("runtime") == runtime_mode() and
            Path(result.get("data_dir", "")).absolute() == data) else None
    except (OSError, ValueError, http.client.HTTPException):
        return None


@contextmanager
def launch_lock(directory):
    import msvcrt
    with (directory / "launcher.lock").open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError("Un autre lancement est en cours. Réessayez dans quelques secondes.") from None
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def preflight():
    offline()
    config = settings()
    if Path(sys.executable).resolve() != Path(config["python"]).resolve():
        raise RuntimeError("Utilisez le Python local approuvé indiqué dans la configuration du runtime sélectionné.")
    if not Path(config["site_packages"]).is_dir():
        raise RuntimeError("Bibliothèques locales absentes. Aucun téléchargement automatique.")
    if not Path("C:/Windows/Fonts/arial.ttf").is_file():
        raise RuntimeError("Police locale Arial absente : export PDF indisponible.")
    try:
        validate_runtime(config)
        check_approval()
    except (OSError, ValueError) as error:
        known = {"MODEL_MISSING": "Modèle small local incomplet ou absent.",
                 "RUNTIME_FILE_CHANGED": "Un composant autorisé est absent ou son empreinte a changé.",
                 "RUNTIME_PATH_CHANGED": "Le chemin d'un composant autorisé a changé.",
                 "RUNTIME_VERSION_CHANGED": "La version d'un composant autorisé a changé."}
        raise RuntimeError(known.get(str(error), "Autorisation ou configuration locale invalide. Consultez docs/PUBLIC_REPRODUCIBILITY.md.")) from None


def launch(args):
    data = check_local_directory(args.data_dir.absolute())
    directory = check_local_directory(ROOT / "work")
    directory.mkdir(exist_ok=True)
    identity = str(data).casefold() + "|" + runtime_mode()
    key = hashlib.sha256(identity.encode()).hexdigest()[:16]
    state = directory / ("launcher-" + key + ".json")
    with launch_lock(directory):
        previous = None
        if state.is_file():
            try:
                previous = read_json(state)
            except (OSError, ValueError):
                pass
        url = previous.get("url") if previous else None
        live = health(url, data) if url else None
        if args.stop:
            if not live:
                print("Aucun serveur LocalASR actif pour ce dossier.")
                return
            if live["busy"]:
                raise RuntimeError("Une transcription est en cours. Attendez sa fin avant d'arrêter LocalASR.")
            token = local_request(url, "/api/config")["token"]
            local_request(url, "/api/shutdown", {}, token)
            deadline = time.monotonic() + 5
            while health(url, data) and time.monotonic() < deadline:
                time.sleep(.1)
            print("LocalASR arrêté. Les fichiers sauvegardés sont conservés.")
            return
        print("Vérification des composants locaux…", flush=True)
        preflight()
        if not live:
            ready = directory / ("ready-" + uuid.uuid4().hex + ".json")
            process = subprocess.Popen([sys.executable, "-I", "-B", "-S", str(ROOT / "run.py"),
                "--port", str(args.port), "--data-dir", str(data), "--ready-file", str(ready)],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            deadline = time.monotonic() + 15
            while not ready.is_file():
                if process.poll() is not None or time.monotonic() > deadline:
                    if process.poll() is None:
                        process.terminate()
                    raise RuntimeError("Démarrage impossible : vérifiez le port choisi et l'accès au dossier local.")
                time.sleep(.1)
            info = read_json(ready)
            url = info["url"]
            if not health(url, data):
                process.terminate()
                raise RuntimeError("Le serveur local n'a pas répondu correctement.")
            write_json(state, {"url": url, "pid": process.pid, "data_dir": str(data)})
        if args.result_file:
            write_json(args.result_file, {"url": url, "reused": bool(live), "data_dir": str(data)}, exclusive=True)
    print("LocalASR : " + url, flush=True)
    if not args.no_browser:
        os.startfile(url)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--runtime", choices=("independent",), help="Environnement indépendant soumis à son autorisation propre")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--stop", action="store_true", help="Après sauvegarde dans le navigateur uniquement")
    parser.add_argument("--result-file", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.runtime:
        os.environ["LOCALASR_RUNTIME"] = args.runtime
    try:
        from app.independence import install_probe
        install_probe()
        launch(args)
    except Exception as error:
        print("LocalASR : " + (str(error) if isinstance(error, RuntimeError) else "Erreur de lancement local (" + type(error).__name__ + ")."), file=sys.stderr)
        if not args.no_browser and sys.stdin.isatty():
            input("Appuyez sur Entrée pour fermer.")
        raise SystemExit(1)
