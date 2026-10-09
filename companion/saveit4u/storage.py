"""Atomic local persistence and a per-profile companion lock."""

import json
import os
from pathlib import Path


def data_directory():
    override = os.environ.get("SAVEIT4U_DATA_DIR")
    if override:
        return Path(override).resolve()
    from .runtime import install_directory
    portable_profile = install_directory() / "portable-data.json"
    if portable_profile.is_file():
        value = json.loads(portable_profile.read_text(encoding="utf-8"))["data_dir"]
        path = Path(value)
        if not path.is_absolute():
            raise ValueError("Portable profile data_dir must be an absolute path.")
        return path.resolve()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SaveIt4U"
    return Path.home() / ".local" / "share" / "saveit4u"


class Store:
    def __init__(self, directory=None):
        self.directory = Path(directory or data_directory())
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "state.json"
        self.lock_file = (self.directory / "host.lock").open("a+b")
        self.lock_file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                if self.lock_file.read(1) == b"":
                    self.lock_file.write(b"0")
                    self.lock_file.flush()
                self.lock_file.seek(0)
                msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock_file.close()
            raise OSError("Another browser already owns the companion queue. Close its SaveIt4U connection first.") from None

    def load(self):
        if not self.path.exists():
            return {"jobs": [], "output_dir": str(Path.home() / "Downloads" / "SaveIt4U")}
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(state.get("jobs"), list) or not isinstance(state.get("output_dir"), str):
                raise ValueError("Invalid saved state")
            return state
        except (ValueError, OSError) as error:
            raise ValueError(f"Cannot read saved queue at {self.path}. Back it up before resetting it: {error}") from error

    def save(self, state):
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(state, file, ensure_ascii=False, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(self.path)

    def close(self):
        self.lock_file.close()
