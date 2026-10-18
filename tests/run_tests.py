import sys
import unittest
import argparse
import os
from pathlib import Path

sys.dont_write_bytecode = True
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
parser = argparse.ArgumentParser()
parser.add_argument("--report", type=Path)
args = parser.parse_args()

# Fail closed if a public test tries to access developer data or a local runtime.
# These tests need only the existing interpreter's standard library.
private_roots = [root / name for name in ("data", "runtime", "test-runs")]
private_files = [root / "models-config/local.json", root / "models-config/runtime-approval.json"]
def deny_private_files(event, values):
    if event in {"open", "os.listdir", "os.scandir", "os.mkdir", "os.remove", "os.rmdir", "ctypes.dlopen"} and values:
        value = values[0]
        if isinstance(value, (str, bytes, os.PathLike)):
            path = Path(os.path.abspath(os.fsdecode(value)))
            if path in private_files or any(path.is_relative_to(p) for p in private_roots):
                raise PermissionError("PUBLIC_TEST_PRIVATE_ACCESS_DENIED")
sys.addaudithook(deny_private_files)
suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern="test_*.py")
result = unittest.TextTestRunner(verbosity=2).run(suite)
if args.report:
    from app.storage import digest, write_json
    code = [*sorted((root / "app").glob("*.py")), *sorted((root / "tests").glob("*.py"))]
    write_json(args.report, {"success": result.wasSuccessful(), "tests_run": result.testsRun,
        "failures": len(result.failures), "errors": len(result.errors),
        "code_sha256": {str(path.relative_to(root)): digest(path) for path in code}}, exclusive=True)
raise SystemExit(0 if result.wasSuccessful() else 1)
