import io
import json
import os
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "companion"))
from saveit4u.engine import media_options, summarize
from saveit4u.manager import Manager
from saveit4u.protocol import MAX_MESSAGE, Writer, read_message
from saveit4u.storage import Store
from saveit4u.transcript import export_transcript, parse_vtt, timestamp
from saveit4u.validation import download_request, youtube_url

URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


class UrlTests(unittest.TestCase):
    def test_canonical_urls_strip_tracking_and_playlists(self):
        for url in [URL + "&list=PL123&t=7", "https://youtu.be/jNQXAC9IVRw?si=abc",
                    "https://www.youtube.com/shorts/jNQXAC9IVRw", "https://m.youtube.com/embed/jNQXAC9IVRw/",
                    "https://www.youtube.com/live/jNQXAC9IVRw"]:
            self.assertEqual(youtube_url(url), URL)

    def test_rejects_spoofing_local_networks_commands_and_invalid_ids(self):
        for value in ["http://youtube.com/watch?v=jNQXAC9IVRw", "https://youtube.com.evil.test/watch?v=jNQXAC9IVRw",
                      "https://youtube.com@127.0.0.1/watch?v=jNQXAC9IVRw", "https://youtube.com:443/watch?v=jNQXAC9IVRw",
                      "file:///etc/passwd", "https://127.0.0.1/watch?v=jNQXAC9IVRw", "--exec calc",
                      "https://youtube.com/watch?v=../secret", "https://youtube.com/playlist?list=x",
                      URL + "&v=abcdefghijk", "https://youtu.be/jNQXAC9IVRw/extra", None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                youtube_url(value)

    def test_download_boundary(self):
        self.assertEqual(download_request({"url": URL})["container"], "mkv")
        for values in [{"quality": "9999"}, {"mode": "playlist"}, {"language": "../../file"},
                       {"container": "exe"}, {"audio": "--exec"}, {"auto_captions": "yes"}, {"mode": "transcript"}]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                download_request({"url": URL, **values})


class ProtocolTests(unittest.TestCase):
    def test_unicode_multiple_frames_and_eof(self):
        buffer = io.BytesIO()
        writer = Writer(buffer)
        writer.send({"title": "اردو — 日本語 🎬"})
        writer.send({"id": "second"})
        buffer.seek(0)
        self.assertEqual(read_message(buffer), {"title": "اردو — 日本語 🎬"})
        self.assertEqual(read_message(buffer), {"id": "second"})
        self.assertIsNone(read_message(buffer))

    def test_partial_reads(self):
        class Partial(io.BytesIO):
            def read(self, length=-1):
                return super().read(min(length, 2))
        buffer = io.BytesIO()
        Writer(buffer).send({"id": "one"})
        self.assertEqual(read_message(Partial(buffer.getvalue())), {"id": "one"})

    def test_invalid_messages(self):
        for data in [struct.pack("=I", MAX_MESSAGE + 1), b"\x04\x00", struct.pack("=I", 9) + b"{}",
                     struct.pack("=I", 2) + b"[]", struct.pack("=I", 0)]:
            with self.subTest(data=data), self.assertRaises((ValueError, EOFError)):
                read_message(io.BytesIO(data))

    def test_thread_safe_frames(self):
        buffer = io.BytesIO()
        writer = Writer(buffer)
        threads = [threading.Thread(target=lambda n=i: writer.send({"id": str(n)})) for i in range(25)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        buffer.seek(0)
        values = [read_message(buffer)["id"] for _ in threads]
        self.assertEqual(len(set(values)), 25)


VTT = """WEBVTT

00:00:00.000 --> 00:00:02.000 align:start position:0%
Hello &amp; <c>world</c>

00:00:02.000 --> 00:00:04.000
world today

00:00:04.000 --> 00:00:06.000
world today

01:02:03.250 --> 01:02:05.700
اردو <00:00:05.500>日本語
"""


class TranscriptTests(unittest.TestCase):
    def test_manual_captions_preserve_repeated_dialogue(self):
        cues = parse_vtt(VTT)
        self.assertEqual([c["text"] for c in cues], ["Hello & world", "world today", "world today", "اردو 日本語"])
        self.assertEqual(cues[-1]["start"], 3723.25)

    def test_automatic_rolling_window_deduplication(self):
        cues = parse_vtt(VTT, deduplicate=True)
        self.assertEqual([c["text"] for c in cues], ["Hello & world", "today", "اردو 日本語"])

    def test_exports_language_suffix_and_valid_srt(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "Test [jNQXAC9IVRw].en.vtt"
            source.write_text(VTT, encoding="utf-8")
            paths = export_transcript(source)
            self.assertEqual([p.name for p in paths], ["Test [jNQXAC9IVRw].en.srt", "Test [jNQXAC9IVRw].en.txt", "Test [jNQXAC9IVRw].en.json"])
            self.assertIn("01:02:03,250 --> 01:02:05,700", paths[0].read_text(encoding="utf-8"))
            self.assertEqual(json.loads(paths[2].read_text(encoding="utf-8"))[0]["text"], "Hello & world")

    def test_millisecond_rounding_carries_into_minutes(self):
        self.assertEqual(timestamp(59.9996), "00:01:00.000")
        self.assertEqual(parse_vtt("WEBVTT\n\nNOTE nothing here"), [])


class EngineTests(unittest.TestCase):
    def test_summary_has_no_media_urls_and_manual_tracks_win(self):
        result = summarize({"id": "jNQXAC9IVRw", "webpage_url": URL, "title": "Test",
                            "formats": [{"height": 2160, "vcodec": "vp9", "url": "SECRET"},
                                        {"height": 1080, "vcodec": "avc1", "ext": "mp4"}],
                            "subtitles": {"en": [{"ext": "vtt", "name": "English", "url": "SECRET"}]},
                            "automatic_captions": {"en": [{"ext": "vtt"}], "ur": [{"ext": "vtt"}]}})
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertEqual(result["heights"], [2160, 1080])
        self.assertEqual(result["mp4_heights"], [1080])
        self.assertFalse(result["captions"][0]["automatic"])

    def test_real_format_selector_keeps_audio_and_respects_quality_cap(self):
        try:
            from yt_dlp import YoutubeDL
        except ImportError:
            self.skipTest("Install yt-dlp to run format selection integration.")
        formats = [
            {"format_id": "aac", "ext": "m4a", "vcodec": "none", "acodec": "mp4a", "url": "https://example.test/audio"},
            {"format_id": "720", "height": 720, "ext": "mp4", "vcodec": "avc1", "acodec": "none", "url": "https://example.test/720"},
            {"format_id": "1080", "height": 1080, "ext": "mp4", "vcodec": "avc1", "acodec": "none", "url": "https://example.test/1080"},
            {"format_id": "2160", "height": 2160, "ext": "webm", "vcodec": "vp9", "acodec": "none", "url": "https://example.test/2160"},
        ]
        with YoutubeDL({"quiet": True}) as downloader:
            for container, quality, expected in [("mkv", "best", "2160"), ("mkv", "720", "720"), ("mp4", "best", "1080")]:
                options = media_options(download_request({"url": URL, "container": container, "quality": quality}))
                selection = list(downloader.build_format_selector(options["format"])(
                    {"formats": formats, "has_merged_format": False, "incomplete_formats": False}))
                self.assertEqual([f["format_id"] for f in selection[0]["requested_formats"]], [expected, "aac"])


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.processes = []
        self.allow_exit = threading.Event()
        self.manager = Manager(lambda event: None, self.root / "state", worker_factory=self.worker)
        self.manager.configure(str(self.root / "downloads"))

    def tearDown(self):
        self.allow_exit.set()
        self.manager.close()
        self.temporary.cleanup()

    def worker(self, request):
        script = "import json,time; print(json.dumps({'type':'progress','phase':'downloading','percent':20}),flush=True); time.sleep(20)"
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
        process = subprocess.Popen([sys.executable, "-u", "-c", script], stdout=subprocess.PIPE,
                                   text=True, encoding="utf-8", **kwargs)
        self.processes.append(process)
        return process

    def wait_for(self, predicate):
        until = time.monotonic() + 5
        while time.monotonic() < until:
            if predicate(): return
            time.sleep(0.02)
        self.fail("Timed out waiting for queue state")

    def test_pause_resume_cancel_and_no_duplicate_workers(self):
        job = self.manager.enqueue({"url": URL})
        self.wait_for(lambda: len(self.processes) == 1)
        self.assertEqual(self.manager.control(job["id"], "pause")["status"], "paused")
        self.assertIsNotNone(self.processes[0].poll())
        self.manager.control(job["id"], "resume")
        self.wait_for(lambda: len(self.processes) == 2)
        self.assertEqual(self.manager.control(job["id"], "cancel")["status"], "cancelled")
        self.wait_for(lambda: self.manager.running is None)
        self.assertEqual(self.manager.snapshot()["jobs"][0]["status"], "cancelled")

    def test_queue_is_sequential_and_duplicates_are_rejected(self):
        first = self.manager.enqueue({"url": URL})
        self.wait_for(lambda: len(self.processes) == 1)
        with self.assertRaises(ValueError): self.manager.enqueue({"url": URL})
        second = self.manager.enqueue({"url": URL, "mode": "audio"})
        self.assertEqual(len(self.processes), 1)
        self.assertEqual(second["status"], "queued")
        self.manager.control(first["id"], "cancel")
        self.wait_for(lambda: len(self.processes) == 2)
        self.manager.control(second["id"], "cancel")

    def test_restart_restores_paused_jobs_and_keeps_files(self):
        job = self.manager.enqueue({"url": URL})
        self.wait_for(lambda: len(self.processes) == 1)
        partial = Path(job["work_folder"]) / "partial.part"
        partial.write_bytes(b"partial content")
        self.manager.close()
        self.manager = Manager(lambda event: None, self.root / "state", worker_factory=self.worker)
        self.assertEqual(self.manager.snapshot()["jobs"][0]["status"], "paused")
        self.assertEqual(partial.read_bytes(), b"partial content")
        self.assertEqual(len(self.processes), 1)

    def test_one_host_per_profile(self):
        with self.assertRaises(OSError): Store(self.root / "state")

    def test_application_update_resumes_active_jobs_but_keeps_user_paused_jobs(self):
        first = self.manager.enqueue({"url": URL})
        self.wait_for(lambda: len(self.processes) == 1)
        second = self.manager.enqueue({"url": URL, "mode": "audio"})
        self.manager.control(second["id"], "pause")
        self.manager.close(resume_active=True)
        self.manager = Manager(lambda event: None, self.root / "state", worker_factory=self.worker)
        self.wait_for(lambda: len(self.processes) == 2)
        jobs = self.manager.snapshot()["jobs"]
        self.assertEqual(jobs[1]["status"], "paused")
        self.assertIn(jobs[0]["status"], {"queued", "downloading"})

    def test_rejects_relative_output_path(self):
        with self.assertRaises(ValueError): self.manager.configure("../escape")

    def test_clear_history_leaves_files_on_disk(self):
        job = self.manager.enqueue({"url": URL})
        self.manager.control(job["id"], "cancel")
        self.assertEqual(self.manager.clear_finished()["jobs"], [])
        self.assertTrue(Path(job["folder"]).is_dir())


class NativeHostTests(unittest.TestCase):
    def test_stdio_hello_unknown_command_and_reconnect_state(self):
        with tempfile.TemporaryDirectory() as folder:
            environment = {**os.environ, "SAVEIT4U_DATA_DIR": folder,
                           "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "companion")}
            buffer = io.BytesIO()
            Writer(buffer).send({"id": "hello", "action": "hello"})
            Writer(buffer).send({"id": "invalid", "action": "execute_shell", "command": "whoami"})
            result = subprocess.run([sys.executable, "-u", "-m", "saveit4u.host"], input=buffer.getvalue(),
                                    capture_output=True, env=environment, timeout=20)
            from saveit4u.ipc import request
            request("shutdown", directory=Path(folder), start=False)
            from saveit4u.storage import Store
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    owned = Store(folder)
                    owned.close()
                    break
                except OSError:
                    time.sleep(0.05)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            responses = io.BytesIO(result.stdout)
            hello = read_message(responses)
            self.assertTrue(hello["ok"])
            self.assertEqual(hello["result"]["jobs"], [])
            self.assertFalse(read_message(responses)["ok"])
            self.assertIsNone(read_message(responses))


if __name__ == "__main__":
    unittest.main()
