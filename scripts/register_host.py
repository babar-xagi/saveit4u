"""Developer registration helper. End users use the EXE installer instead."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "companion"))
from saveit4u.identity import extension_id
from saveit4u.registration import register_native


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extension-id", help="Deprecated: the release identity is discovered automatically")
    args = parser.parse_args()
    if args.extension_id and args.extension_id != extension_id():
        parser.error("Load the current extension package. Its stable identity is paired automatically; no ID is needed.")
    path = register_native(ROOT)
    print(f"SaveIt4U paired automatically. Native manifest: {path}")


if __name__ == "__main__":
    main()
