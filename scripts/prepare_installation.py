"""Prepare a local inventory; never download, install, import packages or approve.

Run only with an already approved interpreter after separate acquisition review.
The output is deliberately pending. Hashes alone do not establish provenance.
"""
import argparse
import hashlib
import importlib.metadata
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def regular_tree(directory):
    if not directory.is_dir():
        raise ValueError("INPUT_DIRECTORY_MISSING")
    if directory.resolve() != directory.absolute():
        raise ValueError("LINKED_INPUT_REFUSED")
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or path.is_junction():
            raise ValueError("LINKED_INPUT_REFUSED")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            yield path


def prepare(config, output):
    config = dict(config)
    for name in ("python", "site_packages", "model_path"):
        path = Path(config[name])
        if not path.is_absolute() or not path.exists() or path.resolve() != path.absolute():
            raise ValueError("INPUT_PATH_INVALID")
        config[name] = str(path.absolute())
    if not re.fullmatch(r"[0-9a-f]{40}", config.get("revision", "")):
        raise ValueError("VERIFIED_MODEL_REVISION_REQUIRED")
    if config.get("device") != "cpu" or config.get("compute_type") != "int8":
        raise ValueError("CPU_INT8_REQUIRED")
    if any(p.get("task") != "transcribe" for p in config["profiles"].values()):
        raise ValueError("TRANSCRIPTION_ONLY")
    site = Path(config["site_packages"])
    model = Path(config["model_path"])
    python = Path(config["python"])
    if not python.is_file():
        raise ValueError("PYTHON_FILE_REQUIRED")
    for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"):
        if not (model / name).is_file() or not (model / name).stat().st_size:
            raise ValueError("MODEL_MISSING")
    output = output.absolute()
    if output.resolve() != output or output.exists() or any(output.is_relative_to(p) or p.is_relative_to(output) for p in (site, model, python.parent)):
        raise ValueError("NEW_SEPARATE_OUTPUT_REQUIRED")
    packages = {}
    for dist in importlib.metadata.distributions(path=[str(site)]):
        name = re.sub(r"[-_.]+", "-", dist.metadata["Name"]).lower()
        if name in packages:
            raise ValueError("DUPLICATE_DISTRIBUTION")
        packages[name] = {"version": dist.version}
    required = {"faster-whisper", "ctranslate2", "av", "numpy", "reportlab", "pillow"}
    if not required.issubset(packages):
        raise ValueError("DEPENDENCIES_MISSING")
    files = []
    for directory, category in ((site, "environment"), (model, "model")):
        for path in regular_tree(directory):
            files.append({"path": str(path), "sha256": digest(path), "package": category})
    files.append({"path": str(python), "sha256": digest(python), "package": "python"})
    # Python standard-library/native dependencies need a separate publisher
    # review. This inventory is intentionally not a provenance attestation.
    inventory = {"schema_version": 1, "packages": packages, "files": files,
                 "provenance_status": "PENDING_EXTERNAL_ARTIFACT_REVIEW"}
    output.mkdir(parents=True, exist_ok=False)
    def write(name, value):
        with (output / name).open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    write("local.json", config)
    write("inventory.json", inventory)
    write("approval.pending.json", {"approved": False,
        "inventory_sha256": digest(output / "inventory.json"),
        **{key: config[key] for key in ("python", "site_packages", "model_path")},
        "excluded_packages": ["hf-xet", "setuptools"],
        "excluded_modules": ["hf_xet", "setuptools", "pkg_resources"],
        "scope": "PENDING human provenance, signature and execution review"})
    return {"files": len(files), "packages": len(packages), "approved": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "runtime/independent")
    args = parser.parse_args()
    print(json.dumps(prepare(json.loads(args.config.read_text("utf-8")), args.output)))


if __name__ == "__main__":
    main()
