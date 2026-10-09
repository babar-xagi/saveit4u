"""Real HTTP downloads, FFmpeg merging/conversion, and caption exports.

Only the YouTube extractor is replaced with a deterministic local fixture.
The media downloader, format selector and postprocessors are real yt-dlp.
"""

import copy
import functools
import http.server
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "companion"))
from saveit4u.engine import download, executable, javascript_runtime

URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class MediaIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from yt_dlp import YoutubeDL
        except ImportError:
            raise unittest.SkipTest("yt-dlp is not installed")
        cls.downloader = YoutubeDL
        cls.ffmpeg, cls.ffprobe = executable("ffmpeg"), executable("ffprobe")
        if not cls.ffmpeg or not cls.ffprobe or not javascript_runtime()[1]:
            raise unittest.SkipTest("Install FFmpeg/FFprobe and a supported JS runtime for media integration tests")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.media = cls.root / "source"
        cls.media.mkdir()
        subprocess.run([cls.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc=size=160x90:rate=10", "-t", "1", "-pix_fmt", "yuv420p", "-c:v", "libx264",
                        "-an", str(cls.media / "video.mp4")], check=True, capture_output=True)
        subprocess.run([cls.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "sine=frequency=440:sample_rate=44100", "-t", "1", "-c:a", "aac",
                        str(cls.media / "audio.m4a")], check=True, capture_output=True)
        (cls.media / "captions.vtt").write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello &amp; welcome.\n", encoding="utf-8")
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(cls.media)))
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        address = f"http://127.0.0.1:{cls.server.server_port}"
        cls.info = {"id": "jNQXAC9IVRw", "title": "Fixture / Video : Test", "duration": 1, "webpage_url": URL,
                    "extractor": "fixture", "extractor_key": "Fixture", "uploader": "Local integration fixture",
                    "formats": [
                        {"format_id": "audio", "url": address + "/audio.m4a", "ext": "m4a", "acodec": "mp4a.40.2", "vcodec": "none"},
                        {"format_id": "video", "url": address + "/video.mp4", "ext": "mp4", "vcodec": "avc1.4d401f", "acodec": "none", "height": 90, "width": 160},
                    ], "subtitles": {"en": [{"ext": "vtt", "name": "English", "url": address + "/captions.vtt"}]}}

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=5)
        cls.temporary.cleanup()

    def run_download(self, name, **options):
        fixture = self.info

        class FixtureDownloader(self.downloader):
            def extract_info(self, url, download=True, **kwargs):
                if url != URL:
                    raise AssertionError("The engine did not use the canonical URL")
                return self.process_ie_result(copy.deepcopy(fixture), download=download)

        folder = self.root / name
        events = []
        with patch("yt_dlp.YoutubeDL", FixtureDownloader):
            result = download({"url": URL, **options}, folder, events.append)
        self.assertTrue(result["files"])
        self.assertTrue(all((folder / file).is_file() for file in result["files"]))
        self.assertFalse(any(item["type"] == "warning" for item in events), events)
        return folder, result

    def stream_types(self, path):
        result = subprocess.run([self.ffprobe, "-v", "error", "-show_streams", "-of", "json", str(path)],
                                capture_output=True, text=True, check=True)
        return [item["codec_type"] for item in json.loads(result.stdout)["streams"]]

    def test_mkv_has_both_video_and_audio_with_all_caption_exports(self):
        folder, result = self.run_download("mkv", mode="video", container="mkv", language="en")
        video = next(folder.glob("*.mkv"))
        self.assertEqual(sorted(self.stream_types(video)), ["audio", "video"])
        self.assertEqual(len(result["files"]), 5)
        self.assertEqual(json.loads(next(folder.glob("*.json")).read_text(encoding="utf-8"))[0]["text"], "Hello & welcome.")

    def test_compatible_mp4_contains_both_streams(self):
        folder, _ = self.run_download("mp4", mode="video", container="mp4")
        self.assertEqual(sorted(self.stream_types(next(folder.glob("*.mp4")))), ["audio", "video"])

    def test_audio_mp3_conversion(self):
        folder, _ = self.run_download("mp3", mode="audio", audio="mp3")
        self.assertEqual(self.stream_types(next(folder.glob("*.mp3"))), ["audio"])

    def test_audio_m4a_keeps_aac_source(self):
        folder, _ = self.run_download("m4a", mode="audio", audio="m4a")
        self.assertEqual(self.stream_types(next(folder.glob("*.m4a"))), ["audio"])

    def test_transcript_only_does_not_download_media(self):
        original = self.info
        self.info = {**original, "formats": [{**original["formats"][1], "vcodec": "vp9", "ext": "webm"}]}
        try:
            # A prior incompatible MP4 selection must not block caption-only export.
            folder, result = self.run_download("transcript", mode="transcript", language="en", container="mp4")
        finally:
            self.info = original
        self.assertEqual({Path(name).suffix for name in result["files"]}, {".vtt", ".srt", ".txt", ".json"})
        self.assertFalse(list(folder.glob("*.mp4")))


if __name__ == "__main__":
    unittest.main()
