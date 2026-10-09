"""yt-dlp integration, executed only inside isolated worker processes."""

import importlib.metadata
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .transcript import export_transcript
from .validation import download_request, youtube_url


def executable(name):
    portable = Path(__file__).resolve().parents[2] / ".tools" / "ffmpeg" / "bin" / (name + (".exe" if os.name == "nt" else ""))
    return str(portable) if portable.is_file() else shutil.which(name)


def javascript_runtime():
    for name, minimum in (("deno", (2, 3)), ("node", (22, 0))):
        path = shutil.which(name)
        if not path:
            continue
        try:
            kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
            output = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=3, check=True, **kwargs).stdout
            match = re.search(r"(\d+)\.(\d+)", output)
            if match and tuple(map(int, match.groups())) >= minimum:
                return name, path
        except (OSError, subprocess.SubprocessError):
            continue
    return None, None


def health():
    def version(package):
        try:
            return importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            return None
    dependencies = {"yt_dlp": version("yt-dlp"), "ejs": version("yt-dlp-ejs"),
                    "ffmpeg": executable("ffmpeg"), "ffprobe": executable("ffprobe"),
                    "runtime": javascript_runtime()[1]}
    return {"ready": all(dependencies.values()), "dependencies": dependencies}


class Logger:
    def __init__(self, emit):
        self.emit = emit

    def debug(self, message):
        pass

    def warning(self, message):
        self.emit({"type": "warning", "message": str(message)[:1000]})

    def error(self, message):
        print(str(message), file=sys.stderr, flush=True)


def base_options(emit):
    runtime, runtime_path = javascript_runtime()
    if not runtime:
        raise ValueError("Install Node 22+ or Deno 2.3+ for YouTube support, then reopen your browser.")
    options = {"quiet": True, "no_warnings": False, "logger": Logger(emit),
            "noplaylist": True, "socket_timeout": 20, "retries": 3, "fragment_retries": 3,
            "cachedir": False, "js_runtimes": {runtime: {"path": runtime_path}},
            "remote_components": set(), "windowsfilenames": True, "restrictfilenames": False}
    if executable("ffmpeg"):
        options["ffmpeg_location"] = str(Path(executable("ffmpeg")).parent)
    return options


def summarize(info):
    formats = info.get("formats") or []
    heights = sorted({int(item["height"]) for item in formats
                      if item.get("height") and item.get("vcodec") != "none"}, reverse=True)
    compatible = sorted({int(item["height"]) for item in formats
                         if item.get("height") and str(item.get("vcodec", "")).startswith("avc1")
                         and item.get("ext") == "mp4"}, reverse=True)
    tracks = {}
    for source, automatic in ((info.get("automatic_captions") or {}, True), (info.get("subtitles") or {}, False)):
        for code, entries in source.items():
            if any(item.get("ext") == "vtt" for item in entries):
                tracks[code] = {"code": code, "name": next((e.get("name") for e in entries if e.get("name")), code),
                                "automatic": automatic}
    return {"id": info.get("id"), "title": str(info.get("title", "YouTube video"))[:500],
            "channel": str(info.get("uploader") or info.get("channel") or "")[:200],
            "duration": info.get("duration"), "heights": heights, "mp4_heights": compatible,
            "captions": sorted(tracks.values(), key=lambda t: (t["automatic"], t["code"])),
            "is_live": bool(info.get("is_live")), "url": youtube_url(info.get("webpage_url"))}


def inspect(url, emit):
    from yt_dlp import YoutubeDL
    with YoutubeDL(base_options(emit)) as ydl:
        info = ydl.extract_info(youtube_url(url), download=False)
    if not info or info.get("_type") in {"playlist", "multi_video"}:
        raise ValueError("Only individual videos are supported.")
    return summarize(info)


def media_options(request):
    if request["mode"] == "transcript":
        return {"skip_download": True, "ignore_no_formats_error": True}
    cap = "" if request["quality"] == "best" else f"[height<={request['quality']}]"
    if request["mode"] == "audio":
        codec = request["audio"]
        selector = {"m4a": "ba[ext=m4a]/ba/b", "opus": "ba[acodec=opus]/ba/b", "mp3": "ba/b"}[codec]
        quality = {"m4a": "256", "opus": "192", "mp3": "0"}[codec]
        return {"format": selector, "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": codec, "preferredquality": quality}]}
    if request["container"] == "mp4":
        # Prefer H.264 + AAC for broad playback compatibility, without re-encoding.
        selector = f"bv[ext=mp4][vcodec^=avc1]{cap}+ba[ext=m4a]/b[ext=mp4][vcodec^=avc1]{cap}"
    else:
        selector = f"bv*{cap}+ba/b{cap}"
    return {"format": selector, "merge_output_format": request["container"],
            "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": request["container"]}]}


def download(data, folder, emit):
    from yt_dlp import YoutubeDL
    request = download_request(data)
    directory = Path(folder).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    options = base_options(emit)
    options.update(media_options(request))
    options.update({"paths": {"home": str(directory)},
                    "outtmpl": {"default": "%(title).100B [%(id)s].%(ext)s"},
                    "continuedl": True, "overwrites": False, "concurrent_fragment_downloads": 4,
                    "nopart": False, "skip_unavailable_fragments": False})
    last_progress = 0.0

    def progress(item):
        nonlocal last_progress
        now = time.monotonic()
        if item.get("status") != "finished" and now - last_progress < 0.4:
            return
        last_progress = now
        total = item.get("total_bytes") or item.get("total_bytes_estimate") or 0
        downloaded = item.get("downloaded_bytes") or 0
        speed = item.get("speed") or 0
        eta = item.get("eta")
        emit({"type": "progress", "phase": "merging" if item.get("status") == "finished" else "downloading",
              "downloaded": downloaded, "total": total,
              "speed": speed if math.isfinite(speed) else 0, "eta": eta,
              "percent": min(100, round(downloaded / total * 100, 1)) if total else None,
              "stream": str(item.get("info_dict", {}).get("format_id") or "")[:100]})

    options["progress_hooks"] = [progress]
    options["postprocessor_hooks"] = [lambda item: emit({"type": "progress", "phase": "processing"})]
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(request["url"], download=False)
        if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}:
            raise ValueError("Wait until this live stream has finished before downloading.")
        emit({"type": "metadata", "metadata": summarize(info)})
        language = request["language"]
        if language:
            manual = info.get("subtitles") or {}
            automatic = info.get("automatic_captions") or {}
            source = manual.get(language) or (automatic.get(language) if request["auto_captions"] else None)
            if not source or not any(track.get("ext") == "vtt" for track in source):
                if request["mode"] == "transcript":
                    raise ValueError("This caption language is not available.")
                emit({"type": "warning", "message": "Selected captions are unavailable; media will still download."})
                language = ""
        # Subtitle errors must not destroy an otherwise successful media download.
        # Run captions separately and report partial success explicitly.
        if request["mode"] != "transcript":
            ydl.process_info(info)
    if language:
        caption_options = base_options(emit)
        caption_options.update({"paths": {"home": str(directory)},
                                "outtmpl": {"default": "%(title).100B [%(id)s].%(ext)s"},
                                "skip_download": True, "writesubtitles": True,
                                "writeautomaticsub": request["auto_captions"],
                                "subtitleslangs": [language], "subtitlesformat": "vtt"})
        try:
            with YoutubeDL(caption_options) as captions:
                captions.extract_info(request["url"], download=True)
            files = list(directory.glob("*.vtt"))
            if not files:
                raise ValueError("No caption file was returned.")
            for file in files:
                export_transcript(file, deduplicate=language not in (info.get("subtitles") or {}))
        except Exception as error:
            if request["mode"] == "transcript":
                raise
            emit({"type": "warning", "message": f"Media saved, but transcript export failed: {error}"[:1000]})
    files = sorted(file.name for file in directory.iterdir()
                   if file.is_file() and file.suffix.lower() in {".mkv", ".mp4", ".m4a", ".mp3", ".opus", ".vtt", ".srt", ".txt", ".json"})
    if not files:
        raise ValueError("The download produced no final files.")
    return {"files": files}
