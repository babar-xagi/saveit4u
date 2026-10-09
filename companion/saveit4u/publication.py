"""Publish finished files into one folder, with collision-safe title filenames."""

import hashlib
import json
import os
import re
import shutil
from pathlib import Path


def safe_title(title):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(title))
    value = " ".join(value.split()).strip(" .")
    value = value.encode("utf-16le")[:240].decode("utf-16le", errors="ignore").rstrip(" .") or "YouTube video"
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", value):
        value = "_" + value
    return value


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def detach_published_files(work_folder):
    """A interrupted publication can leave work files linked to final output.

    Make work copies independent before yt-dlp or caption export writes again,
    so a retry cannot modify a file the user already sees in the output folder.
    Fresh downloads keep the zero-copy publication path.
    """
    work = Path(work_folder)
    for path in list(work.iterdir()):
        if path.name.startswith("media.") and path.is_file() and path.stat().st_nlink > 1:
            temporary = path.with_name(path.name + ".detach.part")
            shutil.copyfile(path, temporary)
            temporary.replace(path)


def publish(files, work_folder, output_folder, title, job_id):
    work, output = Path(work_folder).resolve(), Path(output_folder).resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = work / "publication.json"
    mappings = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
    base = safe_title(title)
    # Keep caption language suffixes together with their media title.
    suffixes = {name: name[len("media"):] if name.startswith("media.") else Path(name).suffix for name in files}
    number = 1
    if not mappings:
        while any((output / (base + (f" ({number})" if number > 1 else "") + suffix)).exists() for suffix in suffixes.values()):
            number += 1
        base += f" ({number})" if number > 1 else ""
    results = []
    for index, name in enumerate(files):
        source = work / name
        if source.parent != work or not source.is_file():
            raise ValueError("Invalid final download file.")
        saved = mappings.get(name)
        if saved:
            destination = output / saved["name"]
            if destination.parent != output:
                raise ValueError("Invalid saved publication path.")
            if destination.exists():
                identical = os.path.samefile(source, destination)
                checksum = saved.get("sha256")
                if identical or (digest(source) == digest(destination) if not checksum else digest(source) == checksum and digest(destination) == checksum):
                    results.append(destination.name)
                    continue
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(job_id)):
            raise ValueError("Invalid publication job ID.")
        temporary = output / f".saveit4u-{job_id}-{index}.part"
        staged = None
        checksum = None
        candidate = base + suffixes[name]
        collision = 1
        while True:
            destination = output / candidate
            mappings[name] = {"name": candidate, "sha256": checksum}
            pending = manifest.with_suffix(".tmp")
            pending.write_text(json.dumps(mappings), encoding="utf-8")
            pending.replace(manifest)
            try:
                # Same-volume publication is zero-copy and atomic; moving the
                # source later cannot overwrite or invalidate the finished file.
                os.link(staged or source, destination)
                break
            except FileExistsError:
                collision += 1
                candidate = f"{base} ({collision}){suffixes[name]}"
            except OSError as error:
                if error.errno not in {1, 18, 38, 95} and getattr(error, "winerror", None) not in {1, 50}:
                    raise
                if staged is None:
                    hasher = hashlib.sha256()
                    with source.open("rb") as original, temporary.open("wb") as copied:
                        while chunk := original.read(1024 * 1024):
                            copied.write(chunk)
                            hasher.update(chunk)
                        copied.flush()
                        os.fsync(copied.fileno())
                    staged, checksum = temporary, hasher.hexdigest()
                    continue
                try:
                    if os.name == "nt":
                        # Windows rename refuses to overwrite, including on exFAT.
                        os.rename(temporary, destination)
                    else:
                        with destination.open("xb") as target, temporary.open("rb") as staged_file:
                            shutil.copyfileobj(staged_file, target, length=1024 * 1024)
                            target.flush()
                            os.fsync(target.fileno())
                    break
                except FileExistsError:
                    collision += 1
                    candidate = f"{base} ({collision}){suffixes[name]}"
        temporary.unlink(missing_ok=True)
        results.append(destination.name)
    return results
