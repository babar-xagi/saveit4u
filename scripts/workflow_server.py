"""Development-only browser harness backed by the REAL frozen native application.

The browser transport is a test adapter; framing, native host, named pipes,
workers, FFmpeg, file publication and metrics run through the packaged EXE.
Never packaged or installed; binds only to loopback with a random request key.
"""

import argparse
import collections
import hashlib
import http.server
import json
import os
import secrets
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "companion"))
from saveit4u.identity import extension_id
from saveit4u.protocol import Writer, read_message


class NativeGateway:
    def __init__(self, executable, profile):
        self.executable, self.profile = executable, profile
        self.process = None
        self.writer = None
        self.lock = threading.RLock()
        self.messages = collections.deque(maxlen=2000)
        self.sequence = 0
        self.session = 0

    def connect(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                return self.session
            self.session += 1
            session = self.session
            environment = {**os.environ, "SAVEIT4U_DATA_DIR": str(self.profile)}
            self.process = subprocess.Popen([str(self.executable), f"chrome-extension://{extension_id()}/"],
                                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                            env=environment, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            self.writer = Writer(self.process.stdin)
            threading.Thread(target=self._read, args=(self.process, session), daemon=True).start()
            return session

    def _read(self, process, session):
        try:
            while True:
                message = read_message(process.stdout)
                if message is None:
                    break
                with self.lock:
                    self.sequence += 1
                    self.messages.append({"sequence": self.sequence, "session": session, "message": message})
        except (ValueError, OSError, EOFError):
            pass

    def send(self, session, message):
        with self.lock:
            if session != self.session or not self.process or self.process.poll() is not None:
                raise ValueError("Native test connection ended.")
            self.writer.send(message)

    def poll(self, session, after):
        with self.lock:
            return {"messages": [item for item in self.messages if item["session"] == session and item["sequence"] > after],
                    "connected": session == self.session and self.process is not None and self.process.poll() is None,
                    "session": self.session}

    def disconnect(self):
        with self.lock:
            process = self.process
            if process and process.poll() is None:
                process.stdin.close()
        if process and process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


class WorkflowHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "extension"), **kwargs)

    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_content(self, value, content_type="application/json"):
        data = value.encode("utf-8") if isinstance(value, str) else json.dumps(value).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        revision = hashlib.sha256(b"".join((ROOT / "extension" / name).read_bytes() for name in ("connection.js", "content.js", "app.js", "app.css"))).hexdigest()[:12]
        marker = '<div style="padding:8px;text-align:center;background:#3b4728;color:#dcf9b4;font:11px system-ui">WORKFLOW TEST · REAL EXE ENGINE · BROWSER TRANSPORT ADAPTER</div>'
        if path == "/__workflow__/adapter.js":
            script = (ROOT / "tests/browser-adapter.js").read_text(encoding="utf-8")
            script = script.replace("__TEST_KEY__", self.server.key).replace("__EXTENSION_ID__", extension_id()).replace("__REVISION__", revision)
            self.send_content(script, "text/javascript; charset=utf-8")
        elif path == "/__workflow__/app.html":
            page = (ROOT / "extension/app.html").read_text(encoding="utf-8")
            page = page.replace('<link rel="stylesheet"', '<base href="/"><link rel="stylesheet"', 1)
            page = page.replace('<script type="module" src="app.js"></script>', f'<script type="module" src="/__workflow__/adapter.js?rev={revision}"></script>', 1)
            page = page.replace("<body>", "<body>" + marker, 1)
            self.send_content(page, "text/html; charset=utf-8")
        elif path == "/watch" or path.startswith("/shorts/"):
            page = f'''<!doctype html><html><head><meta charset="utf-8"><title>Video workflow test</title><link rel="stylesheet" href="/content.css?rev={revision}"><script type="module" src="/__workflow__/adapter.js?rev={revision}"></script></head>
<body style="margin:0;background:#111914;color:#edf5e5;font-family:system-ui">{marker}<main style="padding:70px;max-width:750px"><p style="color:#c1f17b">SAVEIT4U — FULL WORKFLOW CHECK</p><h1>A video page, with one-click downloads.</h1><p>The quality panel is the actual extension content script. It sends requests through the real packaged native host.</p><p><a style="color:#c1f17b" href="/shorts/jNQXAC9IVRw">Test a Shorts route</a> · <a style="color:#c1f17b" href="/__workflow__/app.html?view=manager">Download dashboard</a></p><button id="disconnect" style="padding:12px;border-radius:9px;background:#c1f17b">Test automatic reconnect</button><p id="result"></p></main></body></html>'''
            self.send_content(page, "text/html; charset=utf-8")
        elif path == "/background.js":
            script = (ROOT / "extension/background.js").read_text(encoding="utf-8").replace('"./connection.js"', f'"./connection.js?rev={revision}"')
            self.send_content(script, "text/javascript; charset=utf-8")
        else:
            super().do_GET()

    def do_POST(self):
        if self.headers.get("X-SaveIt4U-Test") != self.server.key:
            self.send_error(403)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length < 100000:
            self.send_error(400)
            return
        value = json.loads(self.rfile.read(length))
        try:
            action = urlsplit(self.path).path
            if action == "/__native__/connect":
                result = {"session": self.server.gateway.connect()}
            elif action == "/__native__/send":
                self.server.gateway.send(value["session"], value["message"])
                result = {"ok": True}
            elif action == "/__native__/poll":
                result = self.server.gateway.poll(value["session"], value.get("after", 0))
            elif action == "/__native__/disconnect":
                self.server.gateway.disconnect()
                result = {"ok": True}
            else:
                raise ValueError("Unknown test transport request")
            self.send_content(result)
        except Exception as error:
            self.send_content({"error": str(error)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, default=ROOT / "dist/SaveIt4U/saveit4u-host.exe")
    parser.add_argument("--profile", type=Path, default=ROOT / ".tmp/browser-workflow")
    args = parser.parse_args()
    args.profile.mkdir(parents=True, exist_ok=True)
    state = args.profile / "state.json"
    if not state.exists():
        state.write_text(json.dumps({"jobs": [], "output_dir": str(args.profile.resolve() / "downloads" / "SaveIt4U")}), encoding="utf-8")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 8767), WorkflowHandler)
    server.key = secrets.token_hex(32)
    server.gateway = NativeGateway(args.executable.resolve(), args.profile.resolve())
    print("Actual native-engine workflow: http://127.0.0.1:8767/watch?v=jNQXAC9IVRw", flush=True)
    try:
        server.serve_forever()
    finally:
        server.gateway.disconnect()
        server.server_close()


if __name__ == "__main__":
    main()
