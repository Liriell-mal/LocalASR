"""Opt-in qualification probe; no effect during ordinary application use.

Reports code paths only. The forbidden root must be explicitly configured.
The Python audit guard is NOT an OS-wide denial of native file access.
"""
import atexit
import json
import os
import sys
from pathlib import Path

_installed = False


def forbidden_root():
    value = os.environ.get("LOCALASR_FORBIDDEN_ROOT")
    if not value or not Path(value).is_absolute():
        raise PermissionError("PROBE_FORBIDDEN_ROOT_REQUIRED")
    return Path(value).absolute()


def within(path, directory):
    if not isinstance(path, (str, bytes, os.PathLike)):
        return False
    try:
        return Path(os.path.abspath(os.fsdecode(path))).is_relative_to(directory)
    except (OSError, ValueError):
        return False


def path_guard(directory, failures):
    def audit(event, args):
        if event in {"open", "os.listdir", "os.scandir", "os.chdir", "os.add_dll_directory", "ctypes.dlopen"}:
            if args and within(args[0], directory):
                failures.append(event)  # No payload, media path or user value.
                raise PermissionError("FORBIDDEN_ROOT_ACCESS")
    return audit


def native_paths():
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.K32EnumProcessModules.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel.K32EnumProcessModules.restype = wintypes.BOOL
    kernel.GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    kernel.GetModuleFileNameW.restype = wintypes.DWORD
    modules = (wintypes.HMODULE * 4096)()
    needed = wintypes.DWORD()
    if not kernel.K32EnumProcessModules(kernel.GetCurrentProcess(), modules, ctypes.sizeof(modules), ctypes.byref(needed)):
        raise RuntimeError("MODULE_ENUMERATION_FAILED")
    if needed.value > ctypes.sizeof(modules):
        raise RuntimeError("MODULE_ENUMERATION_INCOMPLETE")
    paths = []
    for module in modules[:needed.value // ctypes.sizeof(wintypes.HMODULE)]:
        buffer = ctypes.create_unicode_buffer(32768)
        size = kernel.GetModuleFileNameW(module, buffer, len(buffer))
        if not size or size >= len(buffer):
            raise RuntimeError("MODULE_PATH_FAILED")
        paths.append(buffer.value)
    return sorted(set(paths))


def observe_runtime():
    """Technical software origins only; never media, segments or frame locals."""
    from .config import ROOT, runtime_mode, runtime_paths, settings
    from .storage import digest
    inventory = json.loads(runtime_paths()[1].read_text("utf-8"))
    known = {str(Path(item["path"]).absolute()).casefold():item["sha256"] for item in inventory["files"]}
    site = Path(settings()["site_packages"]).absolute()
    native = native_paths()
    modules = {name:str(module.__file__) for name,module in list(sys.modules.items())
               if isinstance(getattr(module, "__file__", None), str)}
    forbidden = forbidden_root()
    windows = Path(os.environ.get("SystemRoot", "C:/Windows")).absolute()
    stdlib = Path(sys.base_prefix) / "Lib"
    unreviewed = []
    changed = []
    for path in sorted(set(native) | set(modules.values())):
        absolute = Path(path).absolute()
        expected = known.get(str(absolute).casefold())
        if expected:
            if digest(absolute) != expected:
                changed.append(str(absolute))
        elif within(path, windows) or (within(path, stdlib) and not within(path, stdlib / "site-packages")) or any(within(path, ROOT / part) for part in ("app", "scripts", "tests")) or absolute in (ROOT / "launch.py", ROOT / "run.py"):
            continue
        else:
            unreviewed.append(str(absolute))
    critical = {name:path for name,path in modules.items() if name in {
        "faster_whisper", "ctranslate2", "ctranslate2._ext", "av", "av._core", "numpy",
        "numpy._core._multiarray_umath", "reportlab", "PIL", "PIL._imaging", "tokenizers",
        "tokenizers.tokenizers", "onnxruntime", "onnxruntime.capi.onnxruntime_pybind11_state",
        "huggingface_hub", "charset_normalizer", "yaml", "yaml._yaml"}}
    violations = [p for p in [*modules.values(), *native, *sys.path] if within(p, forbidden)]
    return {"python":sys.executable, "python_version":sys.version.split()[0], "effective_runtime":runtime_mode(),
        "python_flags":{key:getattr(sys.flags, key) for key in ("isolated", "ignore_environment", "no_user_site", "no_site", "safe_path", "dont_write_bytecode")},
        "environment":{k:os.environ.get(k) for k in ("PYTHONPATH", "PYTHONHOME", "LOCALASR_RUNTIME",
            "HF_HUB_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "HF_HUB_DISABLE_XET")},
        "sys_path":list(sys.path), "critical_imports":critical, "python_code_paths":sorted(set(modules.values())),
        "native_module_paths":native, "candidate_native_paths":[p for p in native if within(p, site)],
        "unreviewed_origins":unreviewed, "changed_components":changed,
        "forbidden_origins":violations, "hf_xet_loaded":"hf_xet" in sys.modules,
        "success":not (unreviewed or changed or violations or "hf_xet" in sys.modules)}


def install_probe():
    global _installed
    destination = os.environ.get("LOCALASR_INDEPENDENCE_REPORTS")
    if not destination or _installed:
        return
    from .config import ROOT, check_local_directory, runtime_mode
    from .security import check_approval
    if runtime_mode() != "independent":
        raise PermissionError("INDEPENDENT_RUNTIME_REQUIRED")
    check_approval()  # Refuse even the probe before candidate authorization.
    output = check_local_directory(Path(destination))
    if not output.is_relative_to(ROOT / "test-runs") or not output.is_dir():
        raise PermissionError("PROBE_OUTPUT_INVALID")
    forbidden = forbidden_root()
    failures = []
    sys.addaudithook(path_guard(forbidden, failures))
    _installed = True

    def save_report():
        role = "worker" if len(sys.argv) > 1 and sys.argv[1] == "worker" else ("server" if Path(sys.argv[0]).name == "run.py" else Path(sys.argv[0]).stem)
        record = {"pid":os.getpid(), "role":role, "blocked_events":failures,
                  "native_file_access_blocked":False}
        try:
            record.update(observe_runtime())
            record["success"] = record["success"] and not failures
        except Exception as error:
            record.update(success=False, error_class=type(error).__name__)
        # Technical paths of software modules only. No source media/transcripts.
        with (output / f"process-{os.getpid()}.json").open("x", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=True, indent=2)
    atexit.register(save_report)
