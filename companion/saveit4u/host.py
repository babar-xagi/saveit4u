"""Native messaging entry point. No network listener, browser cookies or shell API."""

import concurrent.futures
import json
import os
import re
import sys
import threading
from pathlib import Path

from . import __version__
from .engine import health
from .manager import Manager, inspect_video
from .protocol import Writer, read_message


def main():
    if os.name == "nt":
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    writer = Writer(sys.stdout.buffer)
    if len(sys.argv) > 1:
        origin = sys.argv[1]
        manifest_path = Path(__file__).resolve().parents[2] / ".native" / "com.saveit4u.downloader.json"
        try:
            origins = json.loads(manifest_path.read_text(encoding="utf-8"))["allowed_origins"]
            if not re.fullmatch(r"chrome-extension://[a-p]{32}/", origin) or origin not in origins:
                raise ValueError("Unregistered extension origin.")
        except (OSError, ValueError, KeyError) as error:
            print(f"Native host authorization failed: {error}", file=sys.stderr)
            return 1
    disconnected = threading.Event()

    def send(value):
        if not disconnected.is_set():
            try:
                writer.send(value)
            except OSError:
                disconnected.set()
            except ValueError as error:
                try:
                    writer.send({"id": value.get("id"), "ok": False,
                                 "error": f"Companion response could not be sent: {error}. Clear finished history and retry."})
                except OSError:
                    disconnected.set()

    try:
        manager = Manager(send)
    except (OSError, ValueError) as error:
        send({"event": "fatal", "error": f"Cannot start companion: {error}"})
        return 1
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    inspect_slots = threading.BoundedSemaphore(2)

    def respond(request):
        request_id = request.get("id")
        try:
            action = request.get("action")
            if action == "hello":
                result = {"version": __version__, **health(), **manager.snapshot()}
            elif action == "inspect":
                result = inspect_video(request.get("url"))
            elif action == "enqueue":
                if not health()["ready"]:
                    raise ValueError("Companion dependencies are missing. Complete setup before downloading.")
                result = manager.enqueue(request.get("request"))
            elif action in {"pause", "resume", "cancel"}:
                result = manager.control(request.get("job_id"), action)
            elif action == "configure":
                result = manager.configure(request.get("output_dir"))
            elif action == "clear_finished":
                result = manager.clear_finished()
            elif action == "open_folder":
                result = manager.open_folder(request.get("job_id"))
            else:
                raise ValueError("Unknown companion command.")
            send({"id": request_id, "ok": True, "result": result})
        except Exception as error:
            send({"id": request_id, "ok": False, "error": str(error)[:2000]})
        finally:
            if request.get("action") == "inspect":
                inspect_slots.release()

    try:
        while not disconnected.is_set():
            request = read_message(sys.stdin.buffer)
            if request is None:
                break
            request_id = request.get("id")
            if not isinstance(request_id, str) or len(request_id) > 100:
                send({"ok": False, "error": "Request requires a short string ID."})
                continue
            if request.get("action") == "inspect":
                if inspect_slots.acquire(blocking=False):
                    pool.submit(respond, request)
                else:
                    send({"id": request_id, "ok": False, "error": "Two inspections are already running. Try again shortly."})
            else:
                respond(request)
    except (ValueError, EOFError, UnicodeError) as error:
        print(f"Invalid native message: {error}", file=sys.stderr)
    finally:
        disconnected.set()
        manager.close()
        pool.shutdown(wait=True, cancel_futures=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
