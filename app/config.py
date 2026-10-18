import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA_EXTENSIONS = {".wav", ".mp3", ".m4a", ".mp4", ".mov", ".mkv"}


def runtime_mode():
    mode = os.environ.get("LOCALASR_RUNTIME", "independent")
    if mode != "independent":
        raise ValueError("RUNTIME_SELECTION_INVALID")
    return mode


def runtime_paths():
    runtime_mode()  # Never fall back to another environment.
    base = ROOT / "runtime" / "independent"
    return base / "local.json", base / "inventory.json", base / "approval.json"


def settings():
    config = json.loads(runtime_paths()[0].read_text(encoding="utf-8"))
    # Keep older local profile keys usable without modifying existing projects
    # or sealed configurations. New UI requests use the generic automatic key.
    profiles = config["profiles"]
    if "auto" not in profiles:
        for profile in list(profiles.values()):
            if profile.get("language") is None and profile.get("task") == "transcribe":
                profiles["auto"] = dict(profile, label="Détection automatique")
                break
    return config


def offline():
    for key, value in {
        "HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
        "HF_HUB_DISABLE_XET": "1", "TRANSFORMERS_OFFLINE": "1",
        "DO_NOT_TRACK": "1", "PYTHONDONTWRITEBYTECODE": "1",
    }.items():
        os.environ[key] = value


def check_local_directory(path):
    path = Path(path).absolute()
    if str(path).startswith("\\\\"):
        raise ValueError("Un dossier sur un disque local est nécessaire.")
    for parent in (path, *path.parents):
        if parent.exists() and (parent.is_symlink() or parent.is_junction()):
            raise ValueError("Les liens vers d'autres dossiers ne sont pas acceptés.")
    for key in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        cloud = os.environ.get(key)
        if cloud and path.is_relative_to(Path(cloud).resolve()):
            raise ValueError("Choisissez un dossier hors synchronisation cloud.")
    if {p.casefold() for p in path.parts} & {"onedrive", "dropbox", "google drive", "icloud drive"}:
        raise ValueError("Choisissez un dossier hors synchronisation cloud.")
    return path
