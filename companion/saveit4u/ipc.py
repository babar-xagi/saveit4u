"""Authenticated per-user named pipes/Unix socket; bounded JSON, never pickle."""

import hashlib
import json
import os
import subprocess
import time
from multiprocessing.connection import Client

from .protocol import MAX_MESSAGE
from .runtime import command, subprocess_environment
from .storage import data_directory


class MaintenanceError(RuntimeError):
    pass


def maintenance_active(directory=None):
    root = directory or data_directory()
    try:
        value = json.loads((root / "updating.json").read_text(encoding="utf-8"))
        return value.get("until", 0) > time.time()
    except (OSError, ValueError, TypeError):
        return False


def endpoint(directory=None):
    root = directory or data_directory()
    if os.name == "nt":
        identity = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:20]
        return rf"\\.\pipe\saveit4u-{identity}", "AF_PIPE"
    return str(root / "broker.sock"), "AF_UNIX"


def auth_key(directory=None):
    root = directory or data_directory()
    root.mkdir(parents=True, exist_ok=True)
    path = root / "ipc.key"
    if not path.exists():
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(os.urandom(32))
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            pass
    # A second browser can observe the just-created file before its first write
    # is flushed. Wait briefly for that one-time creation, never replace a key.
    deadline = time.monotonic() + 1
    value = path.read_bytes()
    while len(value) < 32 and time.monotonic() < deadline:
        time.sleep(0.01)
        value = path.read_bytes()
    if len(value) != 32:
        raise ValueError("The local connection key is invalid. Repair the application installation.")
    return value


def encode(value):
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_MESSAGE:
        raise ValueError("IPC message is too large. Clear finished download history.")
    return payload


def exchange(request, timeout=15, directory=None):
    address, family = endpoint(directory)
    with Client(address, family=family, authkey=auth_key(directory)) as connection:
        connection.send_bytes(encode(request))
        if not connection.poll(timeout):
            raise TimeoutError("The download engine did not respond in time.")
        response = json.loads(connection.recv_bytes(MAX_MESSAGE).decode("utf-8"))
    if not response.get("ok"):
        raise ValueError(response.get("error", "Download engine request failed."))
    return response["result"]


def ensure_broker(directory=None, timeout=12):
    if maintenance_active(directory):
        raise MaintenanceError("SaveIt4U is updating. The connection will restore automatically when installation finishes.")
    try:
        return exchange({"action": "ping"}, timeout=2, directory=directory)
    except (OSError, EOFError, TimeoutError):
        pass
    environment = subprocess_environment()
    if directory:
        environment["SAVEIT4U_DATA_DIR"] = str(directory)
    root = directory or data_directory()
    root.mkdir(parents=True, exist_ok=True)
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    with (root / "engine.log").open("ab") as log:
        subprocess.Popen(command("service"), stdin=subprocess.DEVNULL,
                         stdout=log, stderr=log, env=environment, **kwargs)
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        try:
            return exchange({"action": "ping"}, timeout=2, directory=directory)
        except (OSError, EOFError, TimeoutError):
            time.sleep(0.15)
    raise OSError(f"Could not start the download engine. Open SaveIt4U to repair the connection. Log: {root / 'engine.log'}")


def request(action, *, directory=None, start=True, **values):
    if maintenance_active(directory):
        raise MaintenanceError("SaveIt4U is updating. The connection will restore automatically when installation finishes.")
    try:
        return exchange({"action": action, **values}, timeout=100 if action == "inspect" else 20, directory=directory)
    except (OSError, EOFError):
        if not start:
            raise
        ensure_broker(directory)
        return exchange({"action": action, **values}, timeout=100 if action == "inspect" else 20, directory=directory)
