"""Native browser bridge to the shared desktop engine."""

import concurrent.futures
import os
import sys
import threading
import uuid

from .identity import allowed_origins
from .ipc import request as rpc
from .ipc import MaintenanceError
from .protocol import Writer, read_message

ACTIONS = {"hello", "inspect", "enqueue", "pause", "resume", "cancel", "configure", "clear_finished", "open_folder", "open_desktop"}


def main():
    origin = next((arg for arg in sys.argv[1:] if arg.startswith("chrome-extension://")), None)
    if origin and origin not in allowed_origins():
        print("This extension is not authorized for SaveIt4U.", file=sys.stderr)
        return 1
    if os.name == "nt":
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    writer = Writer(sys.stdout.buffer)
    disconnected = threading.Event()
    client_id = uuid.uuid4().hex
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    slots = threading.BoundedSemaphore(2)
    monitor_thread = None

    def send(value):
        if disconnected.is_set():
            return
        try:
            writer.send(value)
        except OSError:
            disconnected.set()
        except ValueError as error:
            writer.send({"id": value.get("id"), "ok": False, "error": str(error)})

    def respond(message):
        try:
            action = message.get("action")
            if action not in ACTIONS:
                raise ValueError("Unknown companion command.")
            values = {key: message[key] for key in ("url", "request", "job_id", "output_dir") if key in message}
            send({"id": message["id"], "ok": True, "result": rpc(action, **values)})
        except Exception as error:
            send({"id": message["id"], "ok": False, "error": str(error)[:2000]})
        finally:
            if message.get("action") == "inspect":
                slots.release()

    def monitor():
        previous = {}
        output_dir = None
        while not disconnected.is_set():
            try:
                try:
                    state = rpc("heartbeat", client_id=client_id, origin=origin)
                except ValueError:
                    if disconnected.is_set():
                        return
                    state = rpc("attach", client_id=client_id, origin=origin)
                send({"event": "network", "network": state["network"]})
                for job in state["jobs"]:
                    if previous.get(job["id"]) != job:
                        send({"event": "job", "job": job})
                ids = {job["id"] for job in state["jobs"]}
                if set(previous) - ids or output_dir != state["output_dir"]:
                    send({"event": "snapshot", "snapshot": state})
                output_dir = state["output_dir"]
                previous = {job["id"]: job for job in state["jobs"]}
                send({"event": "engine_status", "ready": state["ready"]})
            except MaintenanceError as error:
                send({"event": "fatal", "error": str(error)})
                disconnected.set()
                return
            except Exception as error:
                send({"event": "engine_error", "error": str(error)[:500]})
            disconnected.wait(1)

    try:
        if origin:
            rpc("attach", client_id=client_id, origin=origin)
            monitor_thread = threading.Thread(target=monitor, name="native-events", daemon=True)
            monitor_thread.start()
        while not disconnected.is_set():
            message = read_message(sys.stdin.buffer)
            if message is None:
                break
            if not isinstance(message.get("id"), str) or len(message["id"]) > 100:
                send({"ok": False, "error": "Invalid request ID."})
                continue
            if message.get("action") == "inspect":
                if slots.acquire(blocking=False):
                    pool.submit(respond, message)
                else:
                    send({"id": message["id"], "ok": False, "error": "Video inspection is busy. Try again shortly."})
            else:
                respond(message)
    except (OSError, ValueError, EOFError, MaintenanceError) as error:
        send({"event": "fatal", "error": str(error)[:1000]})
    finally:
        disconnected.set()
        if monitor_thread:
            monitor_thread.join(timeout=2)
        if origin:
            try:
                rpc("detach", client_id=client_id, origin=origin, start=False)
            except (OSError, ValueError, EOFError, MaintenanceError):
                pass
        pool.shutdown(wait=True, cancel_futures=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
