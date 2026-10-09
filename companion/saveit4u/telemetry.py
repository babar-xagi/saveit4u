"""System receive sampling and aggregate progress across video/audio streams."""

import math
import time


def positive(value):
    return value if isinstance(value, (int, float)) and math.isfinite(value) and value > 0 else 0


def format_size(item, duration=None):
    exact = positive(item.get("filesize"))
    if exact:
        return int(exact), False
    approximate = positive(item.get("filesize_approx"))
    if approximate:
        return int(approximate), True
    bitrate = positive(item.get("tbr"))
    length = positive(duration)
    return (int(bitrate * 1000 / 8 * length), True) if bitrate and length else (0, True)


class TransferProgress:
    def __init__(self, formats=(), duration=None, clock=time.monotonic):
        self.clock = clock
        self.streams = {}
        for item in formats:
            total, estimated = format_size(item, duration)
            self.streams[str(item.get("format_id", "default"))] = {"downloaded": 0, "total": total, "estimated": estimated}
        self.last_time = clock()
        self.last_bytes = 0
        self.speed = 0
        self.started = False

    def update(self, item):
        key = str(item.get("info_dict", {}).get("format_id") or "default")
        state = self.streams.setdefault(key, {"downloaded": 0, "total": 0, "estimated": True})
        state["downloaded"] = positive(item.get("downloaded_bytes"))
        if positive(item.get("total_bytes")):
            state.update(total=item["total_bytes"], estimated=False)
        elif positive(item.get("total_bytes_estimate")):
            state.update(total=item["total_bytes_estimate"], estimated=True)
        if item.get("status") == "finished":
            state.update(total=state["downloaded"], estimated=False)
        total_known = bool(self.streams) and all(positive(s["total"]) for s in self.streams.values())
        total = sum(max(s["total"], s["downloaded"]) for s in self.streams.values()) if total_known else 0
        downloaded = sum(s["downloaded"] for s in self.streams.values())
        now = self.clock()
        elapsed = now - self.last_time
        if not self.started:
            self.started = True
            self.last_bytes, self.last_time = downloaded, now
        elif elapsed >= 0.25:
            sample = max(0, downloaded - self.last_bytes) / elapsed
            self.speed = sample if not self.speed else 0.45 * sample + 0.55 * self.speed
            self.last_bytes, self.last_time = downloaded, now
        speed = self.speed or positive(item.get("speed"))
        estimated = not total_known or any(s["estimated"] for s in self.streams.values())
        eta = max(0, round((total - downloaded) / speed)) if total and speed else None
        return {"downloaded": int(downloaded), "total": int(total), "total_estimated": estimated,
                "speed": speed, "eta": eta,
                "percent": min(100, round(downloaded / total * 100, 1)) if total else None,
                "stream": key, "stream_finished": item.get("status") == "finished"}


class NetworkSampler:
    def __init__(self, counter=None, clock=time.monotonic):
        if counter is None:
            import psutil
            counter = psutil.net_io_counters
        self.counter, self.clock = counter, clock
        self.previous = None
        self.value = {"receive_rate": None, "available": False}

    def sample(self):
        try:
            counters = self.counter()
            if counters is None:
                raise OSError("No network counters")
            now, received = self.clock(), counters.bytes_recv
            rate = 0
            if self.previous:
                previous_time, previous_bytes = self.previous
                elapsed = now - previous_time
                if elapsed > 0:
                    rate = max(0, received - previous_bytes) / elapsed
            self.previous = now, received
            self.value = {"receive_rate": rate, "available": True}
        except Exception:
            self.value = {"receive_rate": None, "available": False}
        return dict(self.value)
