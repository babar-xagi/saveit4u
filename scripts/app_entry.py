"""Shared entry point for the frozen GUI, native bridge and isolated workers."""

import json
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "companion"))


def main():
    if "--worker" in sys.argv:
        from saveit4u.worker import main as run
    elif "--service" in sys.argv:
        from saveit4u.broker import main as run
    elif "--self-test" in sys.argv:
        from saveit4u.engine import health
        from saveit4u.identity import extension_id
        result = {**health(), "extension_id": extension_id()}
        target = Path(sys.argv[sys.argv.index("--self-test") + 1])
        target.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 0 if result["ready"] else 1
    elif any(arg.startswith("chrome-extension://") for arg in sys.argv) or "--native" in sys.argv:
        from saveit4u.host import main as run
    else:
        from saveit4u.desktop import main as run
    return run() or 0


if __name__ == "__main__":
    raise SystemExit(main())
