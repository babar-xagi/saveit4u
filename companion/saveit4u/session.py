"""Explicitly supplied YouTube session, kept in memory and never in queue files."""

import copy
import http.cookiejar
import json
import math
import re
import threading
import time

DOMAINS = {"youtube.com", "www.youtube.com", "m.youtube.com"}


def validate_cookies(values):
    if not isinstance(values, list) or not 0 < len(values) <= 128:
        raise ValueError("No usable YouTube session. Sign in on YouTube in this browser first.")
    if len(json.dumps(values).encode("utf-8")) > 65_536:
        raise ValueError("YouTube session is too large.")
    result = []
    for item in values:
        if not isinstance(item, dict):
            raise ValueError("Invalid YouTube session.")
        domain, name, value, path = (item.get(key) for key in ("domain", "name", "value", "path"))
        if not isinstance(domain, str) or domain.lstrip(".") not in DOMAINS:
            raise ValueError("Only YouTube session cookies are accepted.")
        if not isinstance(name, str) or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,256}", name):
            raise ValueError("Invalid YouTube session cookie name.")
        if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError("Invalid YouTube session cookie value.")
        if not isinstance(path, str) or not path.startswith("/") or len(path) > 256 or any(ord(c) < 32 for c in path):
            raise ValueError("Invalid YouTube session cookie path.")
        expiry = item.get("expirationDate")
        if expiry is not None and (type(expiry) not in (int, float) or not math.isfinite(expiry) or expiry < 0 or expiry > 253402300799):
            raise ValueError("Invalid YouTube session expiry.")
        for flag in ("secure", "httpOnly", "hostOnly"):
            if not isinstance(item.get(flag), bool):
                raise ValueError("Invalid YouTube session cookie flags.")
        if expiry is not None and expiry <= time.time():
            continue
        result.append({"domain": domain, "name": name, "value": value, "path": path,
                       "secure": item["secure"], "httpOnly": item["httpOnly"], "hostOnly": item["hostOnly"], "expirationDate": expiry})
    if not result:
        raise ValueError("YouTube session expired. Sign in in this browser and try again.")
    return result


def apply_cookies(downloader, values):
    if not values:
        return
    for item in validate_cookies(values):
        downloader.cookiejar.set_cookie(http.cookiejar.Cookie(
            version=0, name=item["name"], value=item["value"], port=None, port_specified=False,
            domain=item["domain"], domain_specified=not item["hostOnly"], domain_initial_dot=item["domain"].startswith("."),
            path=item["path"], path_specified=True, secure=item["secure"],
            expires=int(item["expirationDate"]) if item["expirationDate"] is not None else None,
            discard=item["expirationDate"] is None, comment=None, comment_url=None,
            rest={"HttpOnly": None} if item["httpOnly"] else {}, rfc2109=False))


class YouTubeSession:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self.values, self.until = [], 0

    def set(self, values):
        verified = validate_cookies(values)
        with self.lock:
            self.values, self.until = verified, self.clock() + 1200
        return self.status()

    def clear(self):
        with self.lock:
            self.values, self.until = [], 0
        return self.status()

    def get(self):
        with self.lock:
            if self.clock() >= self.until:
                self.values = []
            return copy.deepcopy(self.values)

    def status(self):
        active = bool(self.get())
        return {"active": active, "seconds_left": max(0, int(self.until - self.clock())) if active else 0,
                "message": "YouTube session available for new requests (up to 20 minutes)." if active else "YouTube session not shared. Public videos use guest access."}
