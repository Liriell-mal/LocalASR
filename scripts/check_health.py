"""Static local health check. No model/package import, server or acquisition."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import offline
from launch import preflight


def main():
    offline()
    try:
        preflight()
    except Exception as error:
        # Do not echo paths, authorization contents or native error messages.
        print(json.dumps({"ready": False, "error_class": type(error).__name__}))
        return 1
    print(json.dumps({"ready": True, "inference_tested": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
