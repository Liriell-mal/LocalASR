"""Entry point used with Python -I -B -S: isolated, no startup hooks."""
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

if __name__ == "__main__":
    from app.independence import install_probe
    install_probe()
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        from app.worker import run
        run(Path(sys.argv[2]), sys.argv[3])
    else:
        from app.server import main
        main()
