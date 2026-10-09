"""Validate the entire boundary between the extension and local processes."""

import re
from urllib.parse import parse_qs, urlsplit

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
LANGUAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,34}$")
QUALITIES = {"best", "2160", "1440", "1080", "720", "480", "360"}


def youtube_url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("Enter a YouTube video or Shorts URL.")
    try:
        url = urlsplit(value.strip())
        if url.scheme != "https" or url.username or url.password or url.port is not None:
            raise ValueError
    except ValueError:
        raise ValueError("Use an HTTPS YouTube URL without credentials or a port.") from None
    host = (url.hostname or "").lower()
    if host == "youtu.be":
        video_id = url.path.removeprefix("/")
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        if url.path == "/watch":
            ids = parse_qs(url.query).get("v", [])
            video_id = ids[0] if len(ids) == 1 else ""
        else:
            match = re.fullmatch(r"/(?:shorts|embed|live)/([A-Za-z0-9_-]{11})/?", url.path)
            video_id = match[1] if match else ""
    else:
        raise ValueError("Only individual YouTube videos and Shorts are supported.")
    if not VIDEO_ID.fullmatch(video_id):
        raise ValueError("This URL does not contain a valid YouTube video ID.")
    return f"https://www.youtube.com/watch?v={video_id}"


def download_request(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Invalid download request.")
    mode = data.get("mode", "video")
    quality = data.get("quality", "best")
    container = data.get("container", "mkv")
    audio = data.get("audio", "m4a")
    language = data.get("language", "")
    auto = data.get("auto_captions", True)
    if mode not in {"video", "audio", "transcript"}:
        raise ValueError("Choose video, audio or transcript.")
    if not isinstance(quality, str) or quality not in QUALITIES:
        raise ValueError("Unsupported quality.")
    if container not in {"mkv", "mp4"} or audio not in {"m4a", "mp3", "opus"}:
        raise ValueError("Unsupported media format.")
    if not isinstance(language, str) or (language and not LANGUAGE.fullmatch(language)):
        raise ValueError("Choose an available caption language.")
    if mode == "transcript" and not language:
        raise ValueError("Choose a caption language for transcript export.")
    if not isinstance(auto, bool):
        raise ValueError("Invalid automatic captions setting.")
    return {"url": youtube_url(data.get("url")), "mode": mode, "quality": quality,
            "container": container, "audio": audio, "language": language, "auto_captions": auto}
