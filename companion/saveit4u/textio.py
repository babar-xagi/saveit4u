"""Explicit UTF-8 pipe/diagnostic I/O, including frozen Windows runtimes."""

def write_utf8(stream, value):
    if stream is None:
        return
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(value.encode("utf-8", errors="backslashreplace"))
        buffer.flush()
    else:
        stream.write(value)
        stream.flush()


def configure_worker_streams(*streams):
    # Frozen CPython may ignore PYTHONIOENCODING. Configure explicitly for any
    # library text output; protocol writes still bypass the locale via buffer.
    for stream in streams:
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
