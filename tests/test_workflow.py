import base64
import concurrent.futures
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
import zipfile
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "companion"))
from saveit4u.broker import Broker, MetadataCache
from saveit4u.engine import summarize
from saveit4u.identity import allowed_origins, extension_id
from saveit4u.installation import install_payload, sha256
from saveit4u.ipc import auth_key, endpoint, request, MaintenanceError
from saveit4u.protocol import Writer, read_message
from saveit4u.publication import publish, safe_title, detach_published_files
from saveit4u.registration import register_native
from saveit4u.telemetry import NetworkSampler, TransferProgress

URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


class IdentityTests(unittest.TestCase):
    def test_release_manifest_and_host_share_fixed_identity(self):
        manifest = json.loads((ROOT / "extension/manifest.json").read_text())
        self.assertEqual(extension_id(manifest["key"]), extension_id())
        self.assertEqual(extension_id(), "chmanmeiniefhjgmhngolnghkblmiegp")

    def test_registration_needs_no_id_and_has_no_wildcards(self):
        with tempfile.TemporaryDirectory() as folder:
            path = register_native(folder, write_registry=False)
            manifest = json.loads(path.read_text())
            self.assertEqual(set(manifest["allowed_origins"]), allowed_origins())
            self.assertTrue(Path(manifest["path"]).is_file())
            self.assertNotIn("*", json.dumps(manifest))

    @unittest.skipUnless(os.name == "nt", "Windows native registry integration")
    def test_automatic_windows_registry_registration_without_an_id(self):
        import winreg
        name = "com.saveit4u.test_" + uuid.uuid4().hex
        keys = [rf"Software\{browser}\NativeMessagingHosts\{name}" for browser in (r"Google\Chrome", r"Microsoft\Edge", "Chromium")]
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder) / "saveit4u-host.exe"
            executable.write_bytes(b"integration test; never executed")
            try:
                path = register_native(folder, executable=executable, registration_name=name)
                for location in keys:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, location) as key:
                        self.assertEqual(winreg.QueryValueEx(key, "")[0], str(path))
                self.assertEqual(json.loads(path.read_text())["allowed_origins"], sorted(allowed_origins()))
            finally:
                for location in keys:
                    try:
                        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, location)
                    except FileNotFoundError:
                        pass


class TelemetryTests(unittest.TestCase):
    def test_system_receive_rate_and_counter_reset(self):
        times = iter([10, 12, 13])
        counters = iter([SimpleNamespace(bytes_recv=100), SimpleNamespace(bytes_recv=4194404), SimpleNamespace(bytes_recv=5)])
        sampler = NetworkSampler(counter=lambda: next(counters), clock=lambda: next(times))
        self.assertEqual(sampler.sample()["receive_rate"], 0)
        self.assertEqual(sampler.sample()["receive_rate"], 2097152)
        self.assertEqual(sampler.sample()["receive_rate"], 0)

    def test_network_failure_is_unknown_not_fake_zero(self):
        sampler = NetworkSampler(counter=lambda: None)
        self.assertEqual(sampler.sample(), {"receive_rate": None, "available": False})

    def test_restricted_network_counter_does_not_stop_the_engine(self):
        import psutil
        def denied(): raise psutil.AccessDenied()
        sampler = NetworkSampler(counter=denied)
        self.assertEqual(sampler.sample(), {"receive_rate": None, "available": False})

    def test_video_to_audio_does_not_reset_progress(self):
        clock = [0]
        tracker = TransferProgress([{"format_id": "v", "filesize": 1000}, {"format_id": "a", "filesize": 500}], clock=lambda: clock[0])
        first = tracker.update({"info_dict": {"format_id": "v"}, "downloaded_bytes": 600, "total_bytes": 1000})
        self.assertEqual(first["percent"], 40)
        clock[0] = 1
        tracker.update({"info_dict": {"format_id": "v"}, "status": "finished", "downloaded_bytes": 1000})
        clock[0] = 2
        audio = tracker.update({"info_dict": {"format_id": "a"}, "downloaded_bytes": 50, "total_bytes": 500})
        self.assertEqual(audio["downloaded"], 1050)
        self.assertEqual(audio["total"], 1500)
        self.assertEqual(audio["percent"], 70)
        self.assertFalse(audio["total_estimated"])
        self.assertGreater(audio["speed"], 0)
        self.assertIsNotNone(audio["eta"])

    def test_unknown_totals_become_real_estimates(self):
        tracker = TransferProgress([{"format_id": "v"}])
        unknown = tracker.update({"info_dict": {"format_id": "v"}, "downloaded_bytes": 25})
        self.assertIsNone(unknown["percent"])
        estimate = tracker.update({"info_dict": {"format_id": "v"}, "downloaded_bytes": 50, "total_bytes_estimate": 200})
        self.assertEqual(estimate["percent"], 25)
        self.assertTrue(estimate["total_estimated"])
        exact = tracker.update({"info_dict": {"format_id": "v"}, "downloaded_bytes": 50, "total_bytes": 100})
        self.assertEqual(exact["percent"], 50)
        self.assertFalse(exact["total_estimated"])


class ConnectionSetupTests(unittest.TestCase):
    def test_two_first_connections_wait_for_the_initial_key_write(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            key = root / "ipc.key"
            key.write_bytes(b"")
            expected = b"x" * 32
            writer = threading.Thread(target=lambda: (time.sleep(0.05), key.write_bytes(expected)))
            writer.start()
            self.assertEqual(auth_key(root), expected)
            writer.join()

    def test_updating_application_does_not_respawn_old_broker(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "updating.json").write_text(json.dumps({"until": time.time() + 30}))
            with self.assertRaises(MaintenanceError): request("hello", directory=root)
            self.assertFalse((root / "engine.log").exists())


class CacheTests(unittest.TestCase):
    def test_concurrent_inspections_coalesce_and_cache_expires(self):
        calls = []
        now = [0]
        cache = MetadataCache(ttl=2, clock=lambda: now[0])
        def load(url):
            calls.append(url)
            time.sleep(0.05)
            return {"title": "Example", "url": url}
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(lambda _: cache.get(URL, load), range(5)))
        self.assertEqual(len(calls), 1)
        results[0]["title"] = "Changed"
        self.assertEqual(cache.peek(URL)["title"], "Example")
        now[0] = 3
        cache.get(URL, load)
        self.assertEqual(len(calls), 2)


class PublicationTests(unittest.TestCase):
    def test_same_title_is_flat_unique_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "SaveIt4U"
            for index in range(2):
                work = root / f"work{index}"
                work.mkdir()
                (work / "media.mp4").write_bytes(bytes([index]) * 100)
                (work / "media.en.txt").write_text(f"caption {index}")
                names = publish(["media.mp4", "media.en.txt"], work, output, "English Speaking Practice", f"job{index}")
                expected = "English Speaking Practice" + (" (2)" if index else "")
                self.assertEqual(names, [expected + ".mp4", expected + ".en.txt"])
            self.assertEqual((output / "English Speaking Practice.mp4").read_bytes(), bytes([0]) * 100)
            self.assertEqual((output / "English Speaking Practice (2).mp4").read_bytes(), bytes([1]) * 100)
            self.assertFalse(any(path.is_dir() for path in output.iterdir()))

    def test_publish_recovery_is_idempotent_and_same_volume_is_zero_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            work, output = root / "work", root / "SaveIt4U"
            work.mkdir()
            source = work / "media.mp4"
            source.write_bytes(b"video")
            first = publish([source.name], work, output, "Original title", "job")
            second = publish([source.name], work, output, "Original title", "job")
            self.assertEqual(first, second)
            self.assertTrue(os.path.samefile(source, output / first[0]))
            self.assertEqual(len(list(output.iterdir())), 1)

    def test_windows_invalid_titles_and_path_escape(self):
        self.assertEqual(safe_title("../CON: tutorial?"), "_CON_ tutorial_")
        self.assertEqual(safe_title("CON"), "_CON")
        self.assertLessEqual(len(safe_title("🎬" * 200).encode("utf-16le")), 240)

    def test_retry_cannot_modify_a_previously_published_caption(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            work, output = root / "work", root / "SaveIt4U"
            work.mkdir()
            source = work / "media.en.txt"
            source.write_text("original caption")
            original = publish([source.name], work, output, "Video", "job")[0]
            detach_published_files(work)
            source.write_text("updated caption")
            updated = publish([source.name], work, output, "Video", "job")[0]
            self.assertNotEqual(original, updated)
            self.assertEqual((output / original).read_text(), "original caption")
            self.assertEqual((output / updated).read_text(), "updated caption")


class InstallerTests(unittest.TestCase):
    def payload(self, folder, bad_path=False):
        archive = Path(folder) / "payload.zip"
        files = {"SaveIt4U.exe": b"GUI", "saveit4u-host.exe": b"HOST", "extension/manifest.json": b"{}"}
        if bad_path:
            files["../escape.txt"] = b"escape"
        manifest = {"version": "0.2.0", "extension_id": extension_id(), "files": {name: hashlib.sha256(value).hexdigest() for name, value in files.items()}}
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("release-manifest.json", json.dumps(manifest))
            for name, value in files.items(): bundle.writestr(name, value)
        return archive

    def test_install_pairs_automatically_and_verifies_payload(self):
        with tempfile.TemporaryDirectory() as folder:
            payload = self.payload(folder)
            calls = []
            target = install_payload(payload, Path(folder) / "SaveIt4U", sha256(payload), register=lambda *args, **values: calls.append((args, values)), shortcuts=lambda *args: None)
            self.assertEqual((target / "SaveIt4U.exe").read_bytes(), b"GUI")
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1]["executable"], target / "saveit4u-host.exe")

    def test_rejects_tampering_and_archive_path_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            payload = self.payload(folder)
            with self.assertRaises(ValueError): install_payload(payload, Path(folder) / "SaveIt4U", "0" * 64)
            payload = self.payload(folder, bad_path=True)
            with self.assertRaises(ValueError): install_payload(payload, Path(folder) / "SaveIt4U", sha256(payload))
            self.assertFalse((Path(folder) / "escape.txt").exists())

    def test_failed_registration_rolls_back_previous_application(self):
        with tempfile.TemporaryDirectory() as folder:
            payload = self.payload(folder)
            target = Path(folder) / "SaveIt4U"
            target.mkdir()
            (target / "release-manifest.json").write_text(json.dumps({"extension_id": extension_id()}))
            (target / "old.txt").write_text("keep me")
            calls = [0]
            def registration(*args, **values):
                calls[0] += 1
                if calls[0] == 1: raise OSError("Registration failed")
            with self.assertRaises(OSError): install_payload(payload, target, sha256(payload), register=registration, shortcuts=lambda *args: None)
            self.assertEqual((target / "old.txt").read_text(), "keep me")
            self.assertFalse((target / "SaveIt4U.exe").exists())


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.broker = Broker(self.directory, inspect_loader=lambda url: {"title": "Test", "url": url})
        self.thread = threading.Thread(target=self.broker.serve, daemon=True)
        self.thread.start()
        for _ in range(100):
            try:
                request("ping", directory=self.directory, start=False)
                break
            except OSError: time.sleep(0.02)
        else: self.fail("Broker did not start")

    def tearDown(self):
        request("shutdown", directory=self.directory, start=False)
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive())
        self.temporary.cleanup()

    def test_two_browsers_share_engine_and_reconnect_without_state_loss(self):
        origin = next(iter(allowed_origins()))
        for client in ("chrome", "edge"):
            state = request("attach", directory=self.directory, start=False, client_id=client, origin=origin)
        self.assertEqual(state["connection"]["extension_count"], 2)
        request("configure", directory=self.directory, start=False, output_dir=str(self.directory / "downloads"))
        request("detach", directory=self.directory, start=False, client_id="chrome", origin=origin)
        self.assertEqual(request("snapshot", directory=self.directory, start=False)["connection"]["extension_count"], 1)
        restored = request("attach", directory=self.directory, start=False, client_id="chrome-new", origin=origin)
        self.assertEqual(restored["output_dir"], str(self.directory / "downloads"))
        self.assertEqual(restored["connection"]["extension_count"], 2)

    def test_untrusted_origin_and_bad_ipc_secret_are_rejected(self):
        with self.assertRaises(ValueError): request("attach", directory=self.directory, start=False, client_id="bad", origin="chrome-extension://" + "a" * 32 + "/")
        address, family = endpoint(self.directory)
        with self.assertRaises(AuthenticationError): Client(address, family=family, authkey=b"x" * 32)
        self.assertEqual(request("snapshot", directory=self.directory, start=False)["connection"]["state"], "Disconnected")

    def test_heartbeat_cannot_resurrect_a_detached_browser_session(self):
        origin = next(iter(allowed_origins()))
        request("attach", directory=self.directory, start=False, client_id="test", origin=origin)
        request("detach", directory=self.directory, start=False, client_id="test", origin=origin)
        with self.assertRaises(ValueError): request("heartbeat", directory=self.directory, start=False, client_id="test", origin=origin)
        self.assertEqual(request("snapshot", directory=self.directory, start=False)["connection"]["state"], "Disconnected")

    def test_native_bridge_attaches_and_detaches_from_real_broker(self):
        environment = {**os.environ, "SAVEIT4U_DATA_DIR": str(self.directory), "PYTHONPATH": str(ROOT / "companion")}
        origin = next(iter(allowed_origins()))
        process = subprocess.Popen([sys.executable, "-u", "-m", "saveit4u.host", origin], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
        try:
            Writer(process.stdin).send({"id": "hello", "action": "hello"})
            while True:
                message = read_message(process.stdout)
                if message.get("id") == "hello": break
            self.assertTrue(message["ok"])
            self.assertEqual(message["result"]["connection"]["state"], "Connected")
            process.stdin.close()
            process.wait(timeout=10)
            self.assertEqual(process.returncode, 0, process.stderr.read().decode())
            state = request("snapshot", directory=self.directory, start=False)
            self.assertEqual(state["connection"]["state"], "Disconnected")
        finally:
            if process.poll() is None: process.kill(); process.wait(timeout=5)
            process.stdout.close(); process.stderr.close()


if __name__ == "__main__":
    unittest.main()
