"""Resource and process paths for both source checkouts and bundled EXEs."""

import os
import sys
from pathlib import Path


def install_directory():
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]


def resource_directory():
    return Path(getattr(sys, "_MEIPASS", install_directory()))


def command(mode):
    if getattr(sys, "frozen", False):
        if mode == "desktop":
            return [str(install_directory() / "SaveIt4U.exe")]
        return [str(install_directory() / "saveit4u-host.exe"), f"--{mode}"]
    module = {"worker": "saveit4u.worker", "service": "saveit4u.broker", "desktop": "saveit4u.desktop"}[mode]
    return [sys.executable, "-u", "-m", module]


def subprocess_environment():
    environment = os.environ.copy()
    if not getattr(sys, "frozen", False):
        root = str(Path(__file__).resolve().parents[1])
        environment["PYTHONPATH"] = root + os.pathsep + environment.get("PYTHONPATH", "")
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment
