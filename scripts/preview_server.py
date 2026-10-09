"""Loopback-only UI fixture server. Never part of the packaged extension."""

import http.server
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PreviewHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "extension"), **kwargs)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/__preview__/app.html":
            content = (ROOT / "extension" / "app.html").read_text(encoding="utf-8")
            content = content.replace('<link rel="stylesheet"', '<base href="/"><link rel="stylesheet"', 1)
            content = content.replace('<script type="module" src="app.js">', '<script src="/__preview__/chrome.js"></script><script type="module" src="app.js">', 1)
            content = content.replace('<body>', '<body><div style="padding:8px;text-align:center;background:#394626;color:#ddf8b8;font:11px system-ui">INTERFACE TEST · SIMULATED COMPANION AND DOWNLOADS</div>', 1)
            self.respond(content, "text/html; charset=utf-8")
        elif path == "/__preview__/chrome.js":
            self.respond((ROOT / "tests" / "ui-fixture.js").read_text(encoding="utf-8"), "text/javascript; charset=utf-8")
        else:
            super().do_GET()

    def respond(self, content, content_type):
        data = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    print("Simulated UI preview: http://127.0.0.1:8766/__preview__/app.html?view=manager", flush=True)
    http.server.ThreadingHTTPServer(("127.0.0.1", 8766), PreviewHandler).serve_forever()
