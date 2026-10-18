import hashlib
import importlib.abc
import importlib.machinery
import importlib.metadata
import json
import sys
from pathlib import Path

from .config import ROOT, runtime_paths, settings
from .storage import digest


def deny_external_network(event, args):
    """Server-side Python guard: loopback communication remains available."""
    if event in {"socket.connect", "socket.sendto"}:
        address = args[-1]
        host = address[0] if isinstance(address, tuple) else None
        if host not in {"127.0.0.1", "::1"}:
            raise PermissionError("EXTERNAL_NETWORK_DISABLED")
    elif event in {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"}:
        if args[0] not in {"127.0.0.1", "::1", "localhost", None}:
            raise PermissionError("EXTERNAL_NETWORK_DISABLED")


def check_approval():
    """An authorization is bound to the reviewed inventory, never assumed."""
    _, inventory, approval = runtime_paths()
    if not inventory.is_file() or not approval.is_file():
        raise PermissionError("Le moteur attend l'autorisation des composants locaux recensés.")
    grant = json.loads(approval.read_text(encoding="utf-8"))
    if grant.get("approved") is not True or grant.get("inventory_sha256") != hashlib.sha256(inventory.read_bytes()).hexdigest():
        raise PermissionError("L'autorisation des composants locaux doit être vérifiée.")
    data = json.loads(inventory.read_text(encoding="utf-8-sig"))
    config = settings()
    for key in ("python", "site_packages", "model_path"):
        if Path(config[key]).absolute() != Path(grant[key]).absolute():
            raise PermissionError("RUNTIME_PATH_CHANGED")
    for item in data["files"]:
        file = Path(item["path"])
        if not file.is_file() or str(file.resolve()).casefold() != str(file.absolute()).casefold() or digest(file) != item["sha256"].lower():
            raise PermissionError("RUNTIME_FILE_CHANGED")
    import re
    normalize = lambda name: re.sub(r"[-_.]+", "-", name).lower()
    present = {normalize(d.metadata["Name"]): d.version for d in importlib.metadata.distributions(path=[config["site_packages"]])}
    for name, package in data["packages"].items():
        if present.get(name) != package["version"]:
            raise PermissionError("RUNTIME_VERSION_CHANGED")
    return grant


def approval_present():
    try:
        return json.loads(runtime_paths()[2].read_text("utf-8")).get("approved") is True
    except (OSError, ValueError):
        return False


class ReviewedSourceLoader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        # -B stops writes, but by itself still accepts existing .pyc files.
        # Compile the reviewed source and never use another project's bytecode.
        return self.source_to_code(self.get_data(self.path), self.path)


class ReviewedImports(importlib.abc.MetaPathFinder):
    def __init__(self, site, files, excluded_modules=("hf_xet", "setuptools", "pkg_resources")):
        self.site = Path(site).resolve()
        self.files = {str(Path(item["path"]).resolve()).casefold(): item["sha256"].lower() for item in files}
        self.excluded_modules = set(excluded_modules)

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in self.excluded_modules:
            raise ModuleNotFoundError("Component excluded from LocalASR", name=fullname)
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or not spec.origin or spec.origin in ("built-in", "frozen"):
            return None
        origin = Path(spec.origin).resolve()
        if not origin.is_relative_to(self.site):
            return None
        expected = self.files.get(str(origin).casefold())
        if not expected:
            # Optional converters may try torch/transformers merely on import.
            # They must see an absent optional dependency, never execute it.
            raise ModuleNotFoundError("Component outside the reviewed inventory", name=fullname)
        if digest(origin) != expected:
            raise PermissionError("Un composant a changé depuis sa vérification.")
        if isinstance(spec.loader, importlib.machinery.SourceFileLoader):
            spec.loader = ReviewedSourceLoader(fullname, str(origin))
        return spec


def enable_reviewed_imports():
    check_approval()
    for finder in sys.meta_path:
        if isinstance(finder, ReviewedImports) and finder.site != Path(settings()["site_packages"]).resolve():
            raise PermissionError("RUNTIME_PATH_CHANGED")
    if not any(isinstance(finder, ReviewedImports) for finder in sys.meta_path):
        # The loader itself enforces approval too; direct callers cannot load
        # relocated artifacts merely by selecting the pending candidate.
        _, inventory, approval = runtime_paths()
        data = json.loads(inventory.read_text("utf-8"))
        site = settings()["site_packages"]
        grant = json.loads(approval.read_text("utf-8"))
        allowed = [item for item in data["files"] if item["package"] not in grant["excluded_packages"]]
        sys.meta_path.insert(0, ReviewedImports(site, allowed, grant["excluded_modules"]))
        if site not in sys.path:
            sys.path.append(site)
