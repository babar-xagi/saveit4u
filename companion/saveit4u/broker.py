"""Shared download engine. Browser ports can reconnect without losing jobs."""

import copy
import json
import os
import subprocess
import threading
import time
from multiprocessing import AuthenticationError
from multiprocessing.connection import Listener
from pathlib import Path

from . import __version__
from .engine import health
from .identity import allowed_origins
from .ipc import auth_key, encode, endpoint, maintenance_active
from .manager import Manager, inspect_video, stop_inspections
from .protocol import MAX_MESSAGE
from .storage import data_directory
from .runtime import command, subprocess_environment
from .telemetry import NetworkSampler
from .validation import youtube_url
from .session import YouTubeSession
from .errors import public_error


class MetadataCache:
    def __init__(self, ttl=120, clock=time.monotonic):
        self.ttl, self.clock = ttl, clock
        self.lock = threading.RLock()
        self.values, self.flights = {}, {}

    def peek(self, url):
        with self.lock:
            value = self.values.get(url)
            return copy.deepcopy(value[1]) if value and self.clock() - value[0] < self.ttl else None

    def get(self, url, loader):
        with self.lock:
            cached = self.peek(url)
            if cached:
                return cached
            flight = self.flights.get(url)
            owner = flight is None
            if owner:
                flight = {"event": threading.Event(), "value": None, "error": None}
                self.flights[url] = flight
        if owner:
            try:
                flight["value"] = loader(url)
                with self.lock:
                    self.values[url] = self.clock(), flight["value"]
                    while len(self.values) > 32:
                        self.values.pop(next(iter(self.values)))
            except Exception as error:
                flight["error"] = error
            finally:
                with self.lock:
                    self.flights.pop(url, None)
                    flight["event"].set()
        elif not flight["event"].wait(95):
            raise TimeoutError("Video inspection timed out.")
        if flight["error"]:
            raise ValueError(str(flight["error"]))
        return copy.deepcopy(flight["value"])


class Broker:
    def __init__(self, directory=None, manager_factory=Manager, inspect_loader=inspect_video, sampler=None):
        self.directory = Path(directory or data_directory())
        self.manager = manager_factory(lambda event: None, self.directory)
        self.session = YouTubeSession()
        self.manager.session_provider = self.session.get
        self.inspect_loader = inspect_loader
        self.cache = MetadataCache()
        self.sampler = sampler or NetworkSampler()
        self.stop = threading.Event()
        self.lock = threading.RLock()
        self.clients = {}
        self.inspect_slots = threading.BoundedSemaphore(2)
        self.request_slots = threading.BoundedSemaphore(16)
        self.dependencies = health()
        self.listener = None
        self.resume_after_restart = False

    def snapshot(self):
        with self.lock:
            now = time.monotonic()
            self.clients = {key: item for key, item in self.clients.items() if now - item["seen"] < 10}
            connection = {"state": "Connected" if self.clients else "Disconnected", "extension_count": len(self.clients),
                          "message": "Extension connected automatically." if self.clients else "Waiting for the SaveIt4U extension. It will connect automatically."}
            network = dict(self.sampler.value)
        return {"version": __version__, **self.dependencies, **self.manager.snapshot(), "connection": connection, "network": network,
                "youtube_session": self.session.status()}

    def dispatch(self, request):
        if not isinstance(request, dict):
            raise ValueError("Expected a JSON request object.")
        action = request.get("action")
        if action == "ping":
            return {"version": __version__, "pid": os.getpid()}
        if action in {"attach", "heartbeat", "detach"}:
            client_id = request.get("client_id")
            if not isinstance(client_id, str) or not 1 <= len(client_id) <= 64:
                raise ValueError("Invalid browser session.")
            if request.get("origin") not in allowed_origins():
                raise ValueError("This extension is not authorized for SaveIt4U.")
            with self.lock:
                if action == "detach":
                    self.clients.pop(client_id, None)
                else:
                    if action == "heartbeat" and client_id not in self.clients:
                        raise ValueError("Browser session must attach again after an engine restart.")
                    self.clients[client_id] = {"seen": time.monotonic(), "origin": request["origin"]}
            return self.snapshot()
        if action in {"hello", "snapshot"}:
            return self.snapshot()
        if action in {"youtube_session", "clear_youtube_session"}:
            status = self.session.set(request.get("cookies")) if action == "youtube_session" else self.session.clear()
            with self.lock:
                self.cache = MetadataCache()
            return status
        if action == "inspect":
            url = youtube_url(request.get("url"))
            if not self.inspect_slots.acquire(blocking=False):
                raise ValueError("Two videos are being inspected. Try again in a moment.")
            try:
                cookies = self.session.get()
                loader = (lambda target: self.inspect_loader(target, cookies=cookies)) if cookies else self.inspect_loader
                return self.cache.get(url, loader)
            finally:
                self.inspect_slots.release()
        if action == "enqueue":
            if not self.dependencies["ready"]:
                raise ValueError("The application is missing a bundled component. Reinstall SaveIt4U.")
            data = request.get("request")
            url = youtube_url(data.get("url") if isinstance(data, dict) else None)
            return self.manager.enqueue(data, metadata=self.cache.peek(url))
        if action in {"pause", "resume", "cancel"}:
            return self.manager.control(request.get("job_id"), action)
        if action == "configure":
            return self.manager.configure(request.get("output_dir"))
        if action == "clear_finished":
            return self.manager.clear_finished()
        if action == "open_folder":
            return self.manager.open_folder(request.get("job_id"))
        if action == "open_desktop":
            kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
            subprocess.Popen(command("desktop"), env=subprocess_environment(), **kwargs)
            return {"opened": True}
        if action == "shutdown":
            self.resume_after_restart = bool(request.get("resume_active", False))
            self.stop.set()
            return {"stopped": True}
        raise ValueError("Unknown download engine command.")

    def _handle(self, connection):
        try:
            with connection:
                if not connection.poll(10):
                    return
                message = json.loads(connection.recv_bytes(MAX_MESSAGE).decode("utf-8"))
                try:
                    payload = encode({"ok": True, "result": self.dispatch(message)})
                except Exception as error:
                    payload = encode({"ok": False, "error": public_error(error)})
                connection.send_bytes(payload)
        except (OSError, EOFError, ValueError):
            pass
        finally:
            self.request_slots.release()

    def _accept(self):
        while not self.stop.is_set():
            try:
                connection = self.listener.accept()
            except AuthenticationError:
                continue
            except (OSError, EOFError):
                if self.stop.is_set():
                    return
                continue
            if self.request_slots.acquire(blocking=False):
                threading.Thread(target=self._handle, args=(connection,), daemon=True).start()
            else:
                connection.close()

    def serve(self):
        address, family = endpoint(self.directory)
        if family == "AF_UNIX":
            Path(address).unlink(missing_ok=True)
        self.listener = Listener(address, family=family, authkey=auth_key(self.directory))
        if family == "AF_UNIX":
            Path(address).chmod(0o600)
        threading.Thread(target=self._accept, name="local-rpc", daemon=True).start()
        try:
            while not self.stop.wait(1):
                if maintenance_active(self.directory):
                    self.resume_after_restart = True
                    self.stop.set()
                    break
                with self.lock:
                    self.sampler.sample()
        finally:
            stop_inspections()
            self.manager.close(resume_active=self.resume_after_restart)
            self.listener.close()


def main():
    try:
        Broker().serve()
    except OSError as error:
        print(f"Download engine could not start: {error}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
