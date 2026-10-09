"""A single disposable worker. JSON lines on stdout, diagnostics on stderr."""

import json
import sys

from . import engine
from .textio import configure_worker_streams, write_utf8


def emit(value):
    write_utf8(sys.stdout, json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")


def main():
    configure_worker_streams(sys.stdin, sys.stdout, sys.stderr)
    try:
        stream = getattr(sys.stdin, "buffer", sys.stdin)
        request = json.loads(stream.readline(32_768))
        if request["action"] == "inspect":
            result = engine.inspect(request["url"], emit)
        elif request["action"] == "download":
            result = engine.download(request["request"], request["folder"], emit,
                                     output_folder=request.get("output_folder"), job_id=request.get("job_id"))
        else:
            raise ValueError("Unknown worker action.")
        emit({"type": "result", "result": result})
    except Exception as error:
        emit({"type": "error", "error": str(error)[:2000]})
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
