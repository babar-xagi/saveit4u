"""Chrome's length-prefixed UTF-8 protocol; stdout must contain frames only."""

import json
import struct
import threading

MAX_MESSAGE = 900_000


def read_exact(stream, size):
    chunks = bytearray()
    while len(chunks) < size:
        part = stream.read(size - len(chunks))
        if not part:
            raise EOFError("Truncated native message.")
        chunks.extend(part)
    return bytes(chunks)


def read_message(stream):
    header = stream.read(4)
    if not header:
        return None
    if len(header) < 4:
        header += read_exact(stream, 4 - len(header))
    length = struct.unpack("=I", header)[0]
    if not 0 < length <= MAX_MESSAGE:
        raise ValueError("Native message is too large or empty.")
    value = json.loads(read_exact(stream, length).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object.")
    return value


class Writer:
    def __init__(self, stream):
        self.stream = stream
        self.lock = threading.Lock()

    def send(self, value):
        payload = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_MESSAGE:
            raise ValueError("Response exceeds native message limit.")
        with self.lock:
            self.stream.write(struct.pack("=I", len(payload)))
            self.stream.write(payload)
            self.stream.flush()
