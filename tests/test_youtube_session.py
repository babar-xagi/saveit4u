import copy
import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "companion"))
from saveit4u.broker import Broker
from saveit4u.errors import public_error
from saveit4u.session import YouTubeSession, apply_cookies, validate_cookies
from saveit4u.worker import main

COOKIE = {"domain": ".youtube.com", "name": "SAPISID", "value": "synthetic-session-value",
          "path": "/", "secure": True, "httpOnly": True, "hostOnly": False, "expirationDate": None}
URL = "https://www.youtube.com/watch?v=ARDiDYhDxRc"


class YouTubeSessionTests(unittest.TestCase):
    def test_memory_expiry_and_forget_never_return_secrets_in_status(self):
        now = [0]
        session = YouTubeSession(clock=lambda: now[0])
        self.assertTrue(session.set([COOKIE])["active"])
        self.assertNotIn(COOKIE["value"], json.dumps(session.status()))
        values = session.get()
        values[0]["value"] = "modified"
        self.assertEqual(session.get()[0]["value"], COOKIE["value"])
        now[0] = 1201
        self.assertFalse(session.status()["active"])
        self.assertEqual(session.get(), [])
        session.set([COOKIE])
        self.assertFalse(session.clear()["active"])

    def test_rejects_other_sites_injection_oversize_and_expired_cookies(self):
        for changes in [{"domain": ".google.com"}, {"domain": "youtube.com.evil.test"},
                        {"value": "secret\r\nInjected: x"}, {"name": "a\nb"}, {"path": "no-slash"},
                        {"value": "x" * 4097}, {"expirationDate": float("nan")}, {"secure": "true"}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_cookies([{**COOKIE, **changes}])
        with self.assertRaises(ValueError): validate_cookies([COOKIE] * 129)
        with self.assertRaises(ValueError): validate_cookies([{**COOKIE, "expirationDate": time.time() - 10}])

    def test_downloader_gets_in_memory_cookie_jar_with_no_cookiefile(self):
        from yt_dlp import YoutubeDL
        with YoutubeDL({"quiet": True}) as downloader:
            apply_cookies(downloader, [COOKIE])
            self.assertIn("SAPISID=synthetic-session-value", downloader.cookiejar.get_cookie_header(URL))
            self.assertIsNone(downloader.cookiejar.get_cookie_header("https://example.com/"))
            self.assertIsNone(downloader.params.get("cookiefile"))

    def test_worker_forwards_session_and_reports_clean_verification(self):
        incoming = io.TextIOWrapper(io.BytesIO(json.dumps({"action": "inspect", "url": URL, "cookies": [COOKIE]}).encode()))
        outgoing = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        with patch("sys.stdin", incoming), patch("sys.stdout", outgoing), patch("saveit4u.worker.engine.inspect") as inspect:
            inspect.side_effect = ValueError("\x1b[0;31mERROR:\x1b[0m [youtube] Sign in to confirm you’re not a bot. Use --cookies-from-browser chrome")
            self.assertEqual(main(), 1)
            self.assertEqual(inspect.call_args.kwargs["cookies"], [COOKIE])
        message = outgoing.buffer.getvalue().decode()
        self.assertIn("YouTube verification required", message)
        self.assertNotIn("--cookies", message)
        self.assertNotIn("\\u001b", message)
        self.assertNotIn(COOKIE["value"], message)

    def test_broker_session_invalidates_metadata_and_never_saves_credentials(self):
        calls = []
        def loader(url, cookies=None):
            calls.append(copy.deepcopy(cookies))
            return {"url": url, "title": "Synthetic test video", "qualities": []}
        with tempfile.TemporaryDirectory() as temporary:
            broker = Broker(Path(temporary), inspect_loader=loader)
            try:
                broker.dispatch({"action": "inspect", "url": URL})
                broker.dispatch({"action": "youtube_session", "cookies": [COOKIE]})
                broker.dispatch({"action": "inspect", "url": URL})
                self.assertEqual(calls, [None, [COOKIE]])
                self.assertTrue(broker.snapshot()["youtube_session"]["active"])
                self.assertNotIn(COOKIE["value"], json.dumps(broker.snapshot()))
                broker.dispatch({"action": "clear_youtube_session"})
                self.assertEqual(broker.manager.session_provider(), [])
                broker.dispatch({"action": "inspect", "url": URL})
                self.assertIsNone(calls[-1])
            finally:
                broker.manager.close()
            for path in Path(temporary).rglob("*"):
                if path.is_file(): self.assertNotIn(COOKIE["value"].encode(), path.read_bytes())

    def test_ordinary_error_preserved_without_terminal_controls(self):
        self.assertEqual(public_error("\x1b[31mVideo unavailable\x1b[0m"), "Video unavailable")


if __name__ == "__main__": unittest.main()
