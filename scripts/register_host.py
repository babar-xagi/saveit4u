"""Register the companion for a specific Chrome/Edge extension ID, per user."""

import argparse
import json
import os
import re
import shlex
import sys
from pathlib import Path

HOST = "com.saveit4u.downloader"
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extension-id", required=True, action="append", help="32-letter Chrome/Edge ID; repeat for multiple browsers")
    parser.add_argument("--unregister", action="store_true", help="Remove registration only; retain downloads and application files")
    args = parser.parse_args()
    if any(not re.fullmatch(r"[a-p]{32}", value) for value in args.extension_id):
        parser.error("Extension IDs must be exactly 32 lowercase letters a–p.")
    directory = ROOT / ".native"
    directory.mkdir(exist_ok=True)
    manifest_path = directory / f"{HOST}.json"
    if os.name == "nt":
        import winreg
        locations = [rf"Software\{browser}\NativeMessagingHosts\{HOST}" for browser in (r"Google\Chrome", r"Microsoft\Edge", "Chromium")]
        if args.unregister:
            for location in locations:
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, location)
                except FileNotFoundError:
                    pass
            print("Native companion unregistered. Download files and history were retained.")
            return
        # Batch expands percent signs even inside quotes. Reject unsafe install paths.
        if any(char in str(ROOT) + sys.executable for char in '%\r\n"'):
            parser.error("Move this project and Python to paths without percent signs, newlines or quotes.")
        launcher = directory / "saveit4u-host.cmd"
        launcher.write_text(f'@echo off\r\n"{sys.executable}" -u "{ROOT / "scripts" / "native_entry.py"}" %*\r\n', encoding="utf-8")
    else:
        launcher = directory / "saveit4u-host"
        launcher.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} -u {shlex.quote(str(ROOT / 'scripts' / 'native_entry.py'))} \"$@\"\n", encoding="utf-8")
        launcher.chmod(0o700)
        if sys.platform == "darwin":
            directories = [Path.home() / "Library/Application Support" / browser / "NativeMessagingHosts"
                           for browser in ("Google/Chrome", "Microsoft Edge", "Chromium")]
        else:
            directories = [Path.home() / ".config" / browser / "NativeMessagingHosts"
                           for browser in ("google-chrome", "microsoft-edge", "chromium")]
        if args.unregister:
            for folder in directories:
                (folder / manifest_path.name).unlink(missing_ok=True)
            print("Native companion unregistered. Download files and history were retained.")
            return
    origins = set(f"chrome-extension://{value}/" for value in args.extension_id)
    if manifest_path.exists():
        origins.update(json.loads(manifest_path.read_text(encoding="utf-8"))["allowed_origins"])
    manifest = {"name": HOST, "description": "SaveIt4U local download companion", "path": str(launcher),
                "type": "stdio", "allowed_origins": sorted(origins)}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if os.name == "nt":
        for location in locations:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, location) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest_path))
    else:
        for folder in directories:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / manifest_path.name).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Registered {HOST} for {len(origins)} extension(s). Open extension Setup and check the connection.")


if __name__ == "__main__":
    main()
