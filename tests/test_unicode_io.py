import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "companion"))
from saveit4u.engine import Logger
from saveit4u.worker import emit


class WindowsUnicodeTests(unittest.TestCase):
    def test_worker_preserves_titles_and_caption_names_with_cp1252_stdout(self):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="cp1252", newline="\r\n")
        metadata = {"type": "result", "result": {"title": "آج کی گفتگو — 日本語 🎬", "captions": [{"name": "Māori"}]}}
        with patch("sys.stdout", stream):
            emit(metadata)
        data = raw.getvalue()
        self.assertEqual(json.loads(data.decode("utf-8")), metadata)
        self.assertEqual(data.count(b"\n"), 1)
        self.assertNotIn(b"\r", data)
        stream.detach()

    def test_unicode_diagnostic_cannot_crash_an_inspection(self):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="cp1252")
        message = "ERROR: اردو عنوان — Māori 日本語"
        with patch("sys.stderr", stream):
            Logger(lambda value: None).error(message)
        self.assertEqual(raw.getvalue().decode("utf-8").strip(), message)
        stream.detach()


if __name__ == "__main__":
    unittest.main()
