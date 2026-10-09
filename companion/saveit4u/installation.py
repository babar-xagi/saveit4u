"""Verified per-user installation with staging, rollback and automatic registration."""

import base64
import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from .identity import extension_id
from .registration import register_native, registration_snapshot, restore_registration


def prepare_update(target):
    from .storage import data_directory
    from .ipc import exchange
    portable = target / "portable-data.json"
    root = Path(json.loads(portable.read_text(encoding="utf-8"))["data_dir"]).resolve() if portable.exists() else data_directory()
    root.mkdir(parents=True, exist_ok=True)
    flag = root / "updating.json"
    flag.write_text(json.dumps({"until": time.time() + 90}), encoding="utf-8")
    try:
        exchange({"action": "shutdown", "resume_active": True}, timeout=20, directory=root)
    except (OSError, EOFError, ValueError, TimeoutError):
        pass
    return flag


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def default_install_directory():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Programs" / "SaveIt4U"


def managed_directory(path):
    marker = Path(path) / "release-manifest.json"
    try:
        return json.loads(marker.read_text(encoding="utf-8"))["extension_id"] == extension_id()
    except (OSError, ValueError, KeyError):
        return False


def remove_stage(path, parent):
    actual, boundary = Path(path).resolve(), Path(parent).resolve()
    if actual.parent != boundary or not actual.name.startswith("SaveIt4U.install-"):
        raise ValueError("Refusing to remove a directory outside this installation's staging area.")
    if actual.exists():
        shutil.rmtree(actual)


def create_shortcut(directory):
    if os.name != "nt":
        return
    target = Path(directory) / "SaveIt4U.exe"
    shortcut = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/SaveIt4U.lnk"
    def quote(value):
        return "'" + str(value).replace("'", "''") + "'"
    script = ("$shortcutShell = New-Object -ComObject WScript.Shell; "
              f"$appShortcut = $shortcutShell.CreateShortcut({quote(shortcut)}); "
              f"$appShortcut.TargetPath = {quote(target)}; $appShortcut.WorkingDirectory = {quote(directory)}; "
              f"$appShortcut.IconLocation = {quote(str(target) + ',0')}; $appShortcut.Save()")
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                   check=True, creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True)


def install_payload(archive, destination, expected_sha256, *, register=register_native, shortcuts=create_shortcut, progress=lambda text: None):
    target = Path(destination).expanduser().resolve()
    if target.name != "SaveIt4U":
        raise ValueError("Choose an application folder named SaveIt4U.")
    if target.exists() and not managed_directory(target):
        raise ValueError("The target folder contains other files. Choose a different installation location.")
    if sha256(archive) != expected_sha256:
        raise ValueError("Installer payload verification failed. Download the installer again.")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.parent / f"SaveIt4U.install-{uuid.uuid4().hex}"
    backup = target.parent / f"SaveIt4U.install-backup-{uuid.uuid4().hex}"
    stage.mkdir()
    replaced = False
    had_previous = target.exists()
    previous_registration = registration_snapshot() if register is register_native else None
    maintenance = None
    try:
        progress("Verifying and extracting application files…")
        with zipfile.ZipFile(archive) as source:
            manifest = json.loads(source.read("release-manifest.json"))
            if manifest.get("extension_id") != extension_id():
                raise ValueError("This installer and extension have different release identities.")
            expected = manifest.get("files", {})
            entries = source.infolist()
            if sum(item.file_size for item in entries) > 1024 ** 3 or len(entries) > 20000:
                raise ValueError("Installer payload exceeds the permitted size.")
            for item in entries:
                relative = PurePosixPath(item.filename)
                if relative.is_absolute() or ".." in relative.parts or "\\" in item.filename or ":" in item.filename:
                    raise ValueError("Invalid path in installer payload.")
                if (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Installer payload cannot contain symbolic links.")
                if item.is_dir():
                    continue
                if item.filename != "release-manifest.json" and item.filename not in expected:
                    raise ValueError("Installer contains an unlisted file.")
                output = stage.joinpath(*relative.parts)
                if not output.resolve().is_relative_to(stage.resolve()):
                    raise ValueError("Installer path escaped the staging folder.")
                output.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                with source.open(item) as original, output.open("wb") as extracted:
                    while chunk := original.read(1024 * 1024):
                        extracted.write(chunk)
                        digest.update(chunk)
                if item.filename in expected and digest.hexdigest() != expected[item.filename]:
                    raise ValueError(f"Application file failed verification: {item.filename}")
            if set(expected) != {item.filename for item in entries if not item.is_dir() and item.filename != "release-manifest.json"}:
                raise ValueError("Installer is missing required files.")
        for filename in ("SaveIt4U.exe", "saveit4u-host.exe", "extension/manifest.json"):
            if not (stage / filename).is_file():
                raise ValueError(f"Missing application component: {filename}")
        progress("Connecting Chrome and Edge automatically…")
        if had_previous:
            if register is register_native:
                progress("Closing the previous app safely. Downloads will resume after the update…")
                maintenance = prepare_update(target)
            deadline = time.monotonic() + 15
            while True:
                try:
                    target.rename(backup)
                    break
                except PermissionError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.25)
        stage.rename(target)
        replaced = True
        register(target, executable=target / "saveit4u-host.exe")
        shortcuts(target)
        if backup.exists():
            remove_stage(backup, target.parent)
        progress("Installation complete. The extension connects automatically.")
        return target
    except Exception:
        if replaced:
            failed = target.parent / f"SaveIt4U.install-failed-{uuid.uuid4().hex}"
            target.rename(failed)
            if backup.exists():
                backup.rename(target)
                register(target, executable=target / "saveit4u-host.exe")
            if register is register_native:
                restore_registration(previous_registration)
            remove_stage(failed, target.parent)
        elif backup.exists() and not target.exists():
            backup.rename(target)
        raise
    finally:
        if maintenance:
            maintenance.unlink(missing_ok=True)
        remove_stage(stage, target.parent)
