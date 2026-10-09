"""Install a checksum-verified portable Windows FFmpeg build into this project."""

import hashlib
import json
import os
import platform
import re
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def main():
    if os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit("This helper is for Windows x64. Install ffmpeg and ffprobe using your platform's package manager.")
    folder = ROOT / ".tools" / "ffmpeg"
    binaries = folder / "bin"
    binaries.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(URL + ".sha256", timeout=30) as response:
        checksum_text = response.read(4096).decode("ascii")
    match = re.search(r"\b[a-fA-F0-9]{64}\b", checksum_text)
    if not match:
        raise SystemExit("The vendor did not return a valid SHA-256 checksum. Nothing was installed.")
    expected = match.group().lower()
    archive = folder / "download.zip.part"
    digest = hashlib.sha256()
    with urllib.request.urlopen(URL, timeout=60) as response, archive.open("wb") as target:
        received = 0
        next_report = 10 * 1024 * 1024
        while chunk := response.read(1024 * 1024):
            received += len(chunk)
            if received > 250 * 1024 * 1024:
                raise SystemExit("Download exceeded the expected size limit. Nothing was installed.")
            target.write(chunk)
            digest.update(chunk)
            if received >= next_report:
                print(f"Downloaded {received // 1024 // 1024} MB...", flush=True)
                next_report += 10 * 1024 * 1024
    if digest.hexdigest() != expected:
        archive.unlink()
        raise SystemExit("FFmpeg checksum mismatch. The download was rejected.")
    with zipfile.ZipFile(archive) as source:
        # Extract only expected binaries to fixed filenames, never archive paths.
        for name in ("ffmpeg.exe", "ffprobe.exe"):
            entries = [item for item in source.infolist() if item.filename.endswith("/bin/" + name)]
            if len(entries) != 1 or entries[0].file_size > 200 * 1024 * 1024:
                raise SystemExit(f"Unexpected archive layout for {name}. Nothing was executed.")
            target = binaries / name
            temporary = target.with_suffix(".tmp")
            temporary.write_bytes(source.read(entries[0]))
            temporary.replace(target)
        for name in ("LICENSE", "LICENSE.txt", "README.txt"):
            entries = [item for item in source.infolist() if item.filename.rsplit("/", 1)[-1] == name]
            if entries:
                (folder / name).write_bytes(source.read(entries[0]))
    (folder / "source.json").write_text(json.dumps({"url": URL, "sha256": expected}, indent=2) + "\n", encoding="utf-8")
    archive.unlink()
    print(f"Verified FFmpeg + FFprobe installed at {binaries}. No system PATH changes were made.")


if __name__ == "__main__":
    main()
