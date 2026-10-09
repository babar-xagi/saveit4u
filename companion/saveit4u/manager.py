"""One download at a time, durable queue, and restartable partial transfers."""

import copy
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from .storage import Store
from .runtime import command, subprocess_environment
from .validation import download_request, youtube_url

ACTIVE = {"downloading", "processing", "merging", "queued"}
TERMINAL = {"complete", "failed", "cancelled"}
INSPECTIONS = set()
INSPECTION_LOCK = threading.Lock()


def spawn_worker(request):
    environment = subprocess_environment()
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    process = subprocess.Popen(command("worker"),
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               text=True, encoding="utf-8", env=environment, **kwargs)
    process.stdin.write(json.dumps(request) + "\n")
    process.stdin.close()
    return process


def terminate_tree(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=15, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=5)


def inspect_video(url, cookies=None):
    process = spawn_worker({"action": "inspect", "url": youtube_url(url), "cookies": cookies or []})
    with INSPECTION_LOCK:
        INSPECTIONS.add(process)
    try:
        # stdin was already closed by spawn_worker; communicate must not flush it.
        process.stdin = None
        output, _ = process.communicate(timeout=90)
        result = None
        error = "Could not inspect this video. Update yt-dlp or try again."
        for line in output.splitlines():
            item = json.loads(line)
            if item.get("type") == "result":
                result = item["result"]
            elif item.get("type") == "error":
                error = item["error"]
        if process.returncode or result is None:
            raise ValueError(error)
        return result
    except subprocess.TimeoutExpired:
        terminate_tree(process)
        raise ValueError("Video inspection timed out. Check your connection and try again.") from None
    finally:
        if process.poll() is None:
            terminate_tree(process)
        with INSPECTION_LOCK:
            INSPECTIONS.discard(process)


def stop_inspections():
    with INSPECTION_LOCK:
        processes = list(INSPECTIONS)
    for process in processes:
        terminate_tree(process)


class Manager:
    def __init__(self, emit, directory=None, worker_factory=spawn_worker):
        self.store = Store(directory)
        self.state = self.store.load()
        self.emit = emit
        self.worker_factory = worker_factory
        self.session_provider = lambda: []
        self.condition = threading.Condition(threading.RLock())
        self.running = None
        self.stopping = False
        resume_jobs = set(self.state.pop("restart_jobs", []))
        for job in self.state["jobs"]:
            if "work_folder" not in job and job["status"] != "complete":
                job["work_folder"] = job["folder"]
                job["folder"] = self.state["output_dir"]
            if job["status"] in ACTIVE:
                job["status"] = "paused"
                job["warning"] = "Download engine restarted. Resume to continue available partial files."
            if job["id"] in resume_jobs and job["status"] == "paused":
                job.update(status="queued", warning="Continuing after the application update.")
        self.store.save(self.state)
        self.thread = threading.Thread(target=self._run, name="download-queue", daemon=True)
        self.thread.start()

    def snapshot(self):
        with self.condition:
            return copy.deepcopy(self.state)

    def _save(self):
        self.store.save(self.state)

    def _notify(self, job):
        self.emit({"event": "job", "job": copy.deepcopy(job)})

    def _job(self, job_id):
        if not isinstance(job_id, str):
            raise ValueError("Invalid download ID.")
        for job in self.state["jobs"]:
            if job["id"] == job_id:
                return job
        raise ValueError("Download not found.")

    def enqueue(self, data, metadata=None):
        request = download_request(data)
        with self.condition:
            if len(self.state["jobs"]) >= 100:
                raise ValueError("Queue history is full. Clear finished downloads first.")
            if any(job["request"] == request and job["status"] in ACTIVE | {"paused"}
                   for job in self.state["jobs"]):
                raise ValueError("This download is already in your queue.")
            job_id = uuid.uuid4().hex
            root = Path(self.state["output_dir"]).expanduser().resolve()
            root.mkdir(parents=True, exist_ok=True)
            work = self.store.directory / "work" / job_id
            work.mkdir(parents=True, exist_ok=False)
            variants = [item for item in (metadata or {}).get("qualities", []) if item["container"] == request["container"]] if request["mode"] == "video" else []
            variant = next((item for item in variants if str(item["height"]) == request["quality"]), variants[0] if variants and request["quality"] == "best" else {})
            job = {"id": job_id, "request": request, "title": (metadata or {}).get("title", "YouTube video"), "status": "queued",
                   "created": time.time(), "folder": str(root), "work_folder": str(work), "files": [], "percent": None,
                   "total_estimated": variant.get("estimated", True), "quality_label": variant.get("label", ""),
                   "downloaded": 0, "total": variant.get("size") or 0, "speed": 0, "eta": None, "warning": "", "error": ""}
            self.state["jobs"].append(job)
            self._save()
            self._notify(job)
            self.condition.notify_all()
            return copy.deepcopy(job)

    def control(self, job_id, action):
        with self.condition:
            job = self._job(job_id)
            if action == "resume":
                if job["status"] not in {"paused", "failed"}:
                    raise ValueError("Only paused or failed downloads can be resumed.")
                job.update(status="queued", error="", warning="", speed=0, eta=None)
            elif action in {"pause", "cancel"}:
                if job["status"] not in ACTIVE | {"paused", "failed"}:
                    raise ValueError("This download has already finished.")
                job.update(status="paused" if action == "pause" else "cancelled", speed=0, eta=None)
                if self.running and self.running[0] == job_id:
                    # Keep the queue lock until the old process is dead, so a resume
                    # cannot race its final progress messages or launch two workers.
                    self.running[1]._saveit4u_stopped = True
                    terminate_tree(self.running[1])
            else:
                raise ValueError("Unknown queue action.")
            self._save()
            self._notify(job)
            self.condition.notify_all()
            return copy.deepcopy(job)

    def configure(self, value):
        if not isinstance(value, str) or not value.strip() or len(value) > 1000:
            raise ValueError("Enter an absolute download folder path.")
        path = Path(value.strip()).expanduser()
        if not path.is_absolute():
            raise ValueError("The download folder must be an absolute path.")
        path = path.resolve()
        path.mkdir(parents=True, exist_ok=True)
        with self.condition:
            self.state["output_dir"] = str(path)
            self._save()
        return self.snapshot()

    def clear_finished(self):
        with self.condition:
            self.state["jobs"] = [job for job in self.state["jobs"] if job["status"] not in TERMINAL]
            self._save()
            return self.snapshot()

    def open_folder(self, job_id=None):
        with self.condition:
            folder = Path(self._job(job_id)["folder"] if job_id else self.state["output_dir"]).resolve()
        if not folder.is_dir():
            raise ValueError("The download folder no longer exists.")
        if os.name == "nt":
            os.startfile(str(folder))
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"opened": True}

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.stopping or any(j["status"] == "queued" for j in self.state["jobs"]))
                if self.stopping:
                    return
                job = next(j for j in self.state["jobs"] if j["status"] == "queued")
                try:
                    process = self.worker_factory({"action": "download", "request": job["request"],
                                                   "folder": job.get("work_folder", job["folder"]),
                                                   "output_folder": job["folder"], "job_id": job["id"],
                                                   "cookies": self.session_provider()})
                except Exception as error:
                    job.update(status="failed", error=str(error)[:2000])
                    self._save()
                    self._notify(job)
                    continue
                self.running = (job["id"], process)
                job["status"] = "downloading"
                self._save()
                self._notify(job)
            result = None
            error = "Download process ended without a result. Resume to retry."
            try:
                for line in process.stdout:
                    item = json.loads(line)
                    with self.condition:
                        if getattr(process, "_saveit4u_stopped", False) or job["status"] not in ACTIVE:
                            continue
                        if item.get("type") == "progress":
                            job.update({key: item[key] for key in ("percent", "downloaded", "total", "total_estimated", "speed", "eta", "stream") if key in item})
                            job["status"] = item.get("phase", "downloading")
                            if job["status"] != "downloading":
                                job.update(speed=0, eta=None)
                        elif item.get("type") == "metadata":
                            job["title"] = item["metadata"]["title"]
                        elif item.get("type") == "warning":
                            job["warning"] = item["message"]
                        elif item.get("type") == "result":
                            result = item["result"]
                        elif item.get("type") == "error":
                            error = item["error"]
                        self._notify(job)
                process.wait()
            except Exception as exception:
                error = str(exception)[:2000]
                terminate_tree(process)
            finally:
                process.stdout.close()
            with self.condition:
                if not getattr(process, "_saveit4u_stopped", False) and job["status"] in ACTIVE:
                    if process.returncode == 0 and result:
                        job.update(status="complete", files=result["files"], percent=100, speed=0, eta=None)
                    else:
                        job.update(status="failed", error=error, speed=0, eta=None)
                self.running = None
                self._save()
                self._notify(job)
                if job["status"] == "complete" and job.get("work_folder"):
                    work = Path(job["work_folder"]).resolve()
                    expected = (self.store.directory / "work" / job["id"]).resolve()
                    if work == expected and work.is_relative_to(self.store.directory.resolve()):
                        import shutil
                        shutil.rmtree(work, ignore_errors=True)
                self.condition.notify_all()

    def close(self, resume_active=False):
        with self.condition:
            self.stopping = True
            if resume_active:
                self.state["restart_jobs"] = [job["id"] for job in self.state["jobs"] if job["status"] in ACTIVE]
            for job in self.state["jobs"]:
                if job["status"] in ACTIVE:
                    job.update(status="paused", speed=0, eta=None)
            if self.running:
                self.running[1]._saveit4u_stopped = True
                terminate_tree(self.running[1])
            self._save()
            self.condition.notify_all()
        self.thread.join(timeout=20)
        self.store.close()
