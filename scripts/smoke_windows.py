"""Verify a frozen release without system Python/Node/FFmpeg dependencies.

--live additionally downloads the public 19-second YouTube smoke fixture.
All installation, profile data and output remain in workspace test directories.
"""

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "companion"))
from saveit4u.identity import extension_id
from saveit4u import __version__
from saveit4u.protocol import Writer, read_message
from saveit4u.ipc import exchange


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--inspect-url", action="append", default=[], help="Additional real metadata regression URLs")
    parser.add_argument("--allow-verification", action="store_true", help="Accept a correctly reported YouTube verification restriction for additional URLs")
    args = parser.parse_args()
    release = args.release_dir.resolve()
    test_root = ROOT / ".tmp" / f"release-smoke-{uuid.uuid4().hex}"
    test_root.mkdir(parents=True)
    application = test_root / "SaveIt4U"
    result_file = test_root / "install.json"
    installer = release / f"SaveIt4U-Setup-{__version__}.exe"
    result = subprocess.run([str(installer), "--silent", "--no-register", "--install-dir", str(application), "--result-file", str(result_file)], timeout=120)
    assert result.returncode == 0, result_file.read_text()
    assert json.loads(result_file.read_text())["ok"]
    profile = test_root / "profile"
    output = test_root / "downloads" / "SaveIt4U"
    environment = {**os.environ, "SAVEIT4U_DATA_DIR": str(profile), "PYTHONPATH": "",
                   "PATH": os.path.join(os.environ["SystemRoot"], "System32") + os.pathsep + os.environ["SystemRoot"]}
    environment.pop("PYTHONHOME", None)
    health_file = test_root / "health.json"
    host = application / "saveit4u-host.exe"
    subprocess.run([str(host), "--self-test", str(health_file)], env=environment, check=True, timeout=30)
    health = json.loads(health_file.read_text())
    assert health["ready"] and health["extension_id"] == extension_id()
    for name in ("ffmpeg", "ffprobe", "runtime"):
        assert Path(health["dependencies"][name]).is_relative_to(application)
    process = subprocess.Popen([str(host), f"chrome-extension://{extension_id()}/"], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    incoming = queue.Queue()
    def read():
        try:
            while True:
                value = read_message(process.stdout)
                if value is None: break
                incoming.put(value)
        except Exception as error:
            incoming.put({"error": str(error)})
    threading.Thread(target=read, daemon=True).start()
    writer = Writer(process.stdin)
    def command(action, allow_error=False, **values):
        request_id = uuid.uuid4().hex
        writer.send({"id": request_id, "action": action, **values})
        deadline = time.monotonic() + (110 if action == "inspect" else 40)
        while time.monotonic() < deadline:
            response = incoming.get(timeout=max(0.1, deadline - time.monotonic()))
            if response.get("id") == request_id:
                if not response["ok"] and allow_error: return response
                assert response["ok"], response
                return response["result"]
        raise TimeoutError("Frozen native application did not respond")
    report = {"installation": True, "bundled_components": health, "profile": str(profile), "output": str(output)}
    try:
        hello = command("hello")
        assert hello["connection"]["state"] == "Connected"
        command("configure", output_dir=str(output))
        report["native_connection"] = True
        synthetic = {"domain": ".youtube.com", "name": "SaveIt4UTest", "value": "synthetic-session-fixture", "path": "/", "secure": True, "httpOnly": True, "hostOnly": False}
        assert command("youtube_session", cookies=[synthetic])["active"]
        snapshot = command("hello")
        assert snapshot["youtube_session"]["active"] and synthetic["value"] not in json.dumps(snapshot)
        assert not command("clear_youtube_session")["active"]
        assert synthetic["value"] not in (profile / "state.json").read_text(encoding="utf-8")
        report["native_session_share_forget"] = "synthetic fixture only; no browser credentials accessed"
        if args.inspect_url:
            inspections = []
            for url in args.inspect_url:
                metadata = command("inspect", url=url, allow_error=args.allow_verification)
                if metadata.get("ok") is False:
                    assert "YouTube verification required" in metadata["error"], metadata
                    assert "\x1b" not in metadata["error"] and "--cookies" not in metadata["error"], metadata
                    inspections.append({"url": url, "verification_required": True, "error": metadata["error"]})
                    continue
                assert metadata["qualities"], metadata
                inspections.append({"id": metadata["id"], "title": metadata["title"], "caption_languages": len(metadata["captions"]), "qualities": len(metadata["qualities"])})
            report["additional_inspections"] = inspections
        if args.live:
            url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
            metadata = command("inspect", url=url)
            assert metadata["qualities"]
            job = command("enqueue", request={"url": url, "mode": "video", "container": "mkv", "quality": "best", "language": "en"})
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                state = command("hello")
                saved = next(item for item in state["jobs"] if item["id"] == job["id"])
                if saved["status"] in {"complete", "failed"}: break
                time.sleep(0.5)
            assert saved["status"] == "complete", saved
            assert not saved["warning"], saved
            assert len(saved["files"]) == 5
            assert not any(item.is_dir() for item in output.iterdir())
            media = next(output.glob("*.mkv"))
            probe = subprocess.run([health["dependencies"]["ffprobe"], "-v", "error", "-show_streams", "-of", "json", str(media)], env=environment, capture_output=True, text=True, check=True)
            streams = sorted(item["codec_type"] for item in json.loads(probe.stdout)["streams"])
            assert streams == ["audio", "video"]
            report["live_download"] = {"files": saved["files"], "streams": streams, "title": metadata["title"], "flat_folder": True}
        print(json.dumps(report, indent=2), flush=True)
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=5)
        try:
            exchange({"action": "shutdown"}, directory=profile)
        except (OSError, ValueError):
            pass
        process.stdout.close(); process.stderr.close()
    (test_root / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
