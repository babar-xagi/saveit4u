"""Automatic fixed-identity native registration for the Windows installer."""

import json
import os
import re
import shlex
import sys
from pathlib import Path

from .identity import HOST_NAME, allowed_origins


def registration_snapshot():
    if os.name != "nt":
        return None
    import winreg
    result = {}
    for browser in (r"Google\Chrome", r"Microsoft\Edge", "Chromium"):
        location = rf"Software\{browser}\NativeMessagingHosts\{HOST_NAME}"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, location) as key:
                result[location] = winreg.QueryValueEx(key, "")[0]
        except FileNotFoundError:
            result[location] = None
    return result


def restore_registration(snapshot):
    if snapshot is None:
        return
    import winreg
    for location, value in snapshot.items():
        if value is None:
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, location)
            except FileNotFoundError:
                pass
        else:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, location) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, value)
def native_manifest(launcher):
    return {"name": HOST_NAME, "description": "SaveIt4U download application", "path": str(Path(launcher).resolve()),
            "type": "stdio", "allowed_origins": sorted(allowed_origins())}


def register_native(directory, executable=None, write_registry=True, registration_name=HOST_NAME):
    if not re.fullmatch(r"[a-z0-9_]+(?:\.[a-z0-9_]+)*", registration_name):
        raise ValueError("Invalid native host registration name.")
    root = Path(directory).resolve()
    folder = root / ".native"
    folder.mkdir(parents=True, exist_ok=True)
    if executable:
        launcher = Path(executable).resolve()
        if not launcher.is_file():
            raise ValueError("The SaveIt4U host executable is missing.")
    elif os.name == "nt":
        if any(char in str(root) + sys.executable for char in '%\r\n"'):
            raise ValueError("The install path contains unsupported command-launcher characters.")
        launcher = folder / "saveit4u-host.cmd"
        launcher.write_text(f'@echo off\r\n"{sys.executable}" -u "{root / "scripts" / "native_entry.py"}" %*\r\n', encoding="utf-8")
    else:
        launcher = folder / "saveit4u-host"
        launcher.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} -u {shlex.quote(str(root / 'scripts' / 'native_entry.py'))} \"$@\"\n", encoding="utf-8")
        launcher.chmod(0o700)
    manifest = native_manifest(launcher)
    manifest["name"] = registration_name
    path = folder / f"{registration_name}.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if write_registry:
        if os.name == "nt":
            import winreg
            for browser in (r"Google\Chrome", r"Microsoft\Edge", "Chromium"):
                key_path = rf"Software\{browser}\NativeMessagingHosts\{registration_name}"
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(path))
        else:
            directories = ([Path.home() / "Library/Application Support" / browser / "NativeMessagingHosts" for browser in ("Google/Chrome", "Microsoft Edge", "Chromium")]
                           if sys.platform == "darwin" else [Path.home() / ".config" / browser / "NativeMessagingHosts" for browser in ("google-chrome", "microsoft-edge", "chromium")])
            for target in directories:
                target.mkdir(parents=True, exist_ok=True)
                (target / path.name).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path
