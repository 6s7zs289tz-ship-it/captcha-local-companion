"""Exercise the compiled native bridge with a mock engine; no OCR model is loaded."""
import ctypes
import json
import os
import pathlib
import struct
import subprocess
import sys
import time
import unittest

ROOT = pathlib.Path(sys.argv.pop(1))
HOST = ROOT / "0.1.1" / "native" / "captcha-local-host.exe"
ORIGIN = "chrome-extension://" + "a" * 32 + "/"


def running(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel.CloseHandle(handle)


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.process = subprocess.Popen(
            [str(HOST), ORIGIN], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW
        )
        self.pidfile = ROOT / "0.1.1" / "mock-worker-pid.txt"
        self.pidfile.unlink(missing_ok=True)
        self.started = ROOT / "0.1.1" / "mock-solve-started.txt"
        self.started.unlink(missing_ok=True)

    def tearDown(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            self.process.wait(timeout=5)
        self.process.stdin.close()
        self.process.stdout.close()
        self.process.stderr.close()

    def request(self, kind, payload=None):
        message = {"id": "测试-1", "type": kind}
        if payload is not None:
            message["payload"] = payload
        data = json.dumps(message, ensure_ascii=False).encode("utf-8")
        self.process.stdin.write(struct.pack("<I", len(data)) + data)
        self.process.stdin.flush()
        response = self.read_response()
        self.assertEqual(response["id"], "测试-1")
        return response

    def read_response(self):
        header = self.process.stdout.read(4)
        self.assertEqual(len(header), 4)
        size, = struct.unpack("<I", header)
        self.assertLessEqual(size, 1_000_000)
        response = json.loads(self.process.stdout.read(size))
        return response

    def send_slow(self):
        message = {"id": "slow-1", "type": "SOLVE", "payload": {"imageBase64": "AA==", "requestId": "slow"}}
        data = json.dumps(message).encode("utf-8")
        self.process.stdin.write(struct.pack("<I", len(data)) + data)
        self.process.stdin.flush()
        deadline = time.monotonic() + 5
        while not self.started.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(self.started.exists(), "mock recognition did not start")
        return int(self.pidfile.read_text())

    def assert_worker_stopped(self, pid):
        deadline = time.monotonic() + 5
        while running(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(running(pid))

    def test_stop_interrupts_active_recognition(self):
        pid = self.send_slow()
        start = time.monotonic()
        message = json.dumps({"id": "stop-1", "type": "STOP"}).encode("utf-8")
        self.process.stdin.write(struct.pack("<I", len(message)) + message)
        self.process.stdin.flush()
        replies = {reply["id"]: reply for reply in (self.read_response(), self.read_response())}
        self.assertTrue(replies["stop-1"]["ok"])
        self.assertFalse(replies["slow-1"]["ok"])
        self.assertLess(time.monotonic() - start, 5)
        self.assert_worker_stopped(pid)

    def test_disconnect_interrupts_active_recognition(self):
        pid = self.send_slow()
        start = time.monotonic()
        self.process.stdin.close()
        self.assertEqual(self.process.wait(timeout=5), 0)
        self.assertLess(time.monotonic() - start, 5)
        self.assert_worker_stopped(pid)

    def test_parallel_recognition_is_bounded(self):
        self.send_slow()
        response = self.request("SOLVE", {"imageBase64": "AA=="})
        self.assertFalse(response["ok"])
        self.process.stdin.close()
        self.process.wait(timeout=5)
    def test_ping_does_not_create_worker(self):
        response = self.request("PING")
        self.assertTrue(response["ok"])
        self.assertEqual(response["payload"]["version"], "0.1.1")
        self.assertFalse(response["payload"]["engineLoaded"])
        self.assertFalse(self.pidfile.exists())

    def test_mcp_initialization_solve_and_stop(self):
        response = self.request("SOLVE", {"imageBase64": "AA==", "expectedLength": 4, "hintChars": "AB12", "requestId": "图片-1"})
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["payload"]["text"], "AB12")
        self.assertEqual(response["payload"]["requestId"], "图片-1")
        pid = int(self.pidfile.read_text())
        self.assertTrue(running(pid))
        self.assertTrue(self.request("PING")["payload"]["engineLoaded"])
        self.assertTrue(self.request("STOP")["payload"]["stopped"])
        self.assert_worker_stopped(pid)
        self.assertFalse(self.request("PING")["payload"]["engineLoaded"])

    def test_browser_force_close_releases_owned_worker(self):
        self.assertTrue(self.request("SOLVE", {"imageBase64": "AA=="})["ok"])
        pid = int(self.pidfile.read_text())
        self.process.kill()
        self.process.wait(timeout=5)
        self.assert_worker_stopped(pid)

    def test_normal_disconnect_releases_owned_worker(self):
        self.assertTrue(self.request("SOLVE", {"imageBase64": "AA=="})["ok"])
        pid = int(self.pidfile.read_text())
        self.process.stdin.close()
        self.process.wait(timeout=5)
        self.assert_worker_stopped(pid)

    def test_invalid_arguments_do_not_create_worker(self):
        response = self.request("SOLVE", {"imageBase64": "AA==", "expectedLength": True})
        self.assertFalse(response["ok"])
        self.assertFalse(self.pidfile.exists())
        self.assertTrue(self.request("PING")["ok"])

    def test_unknown_operation_does_not_create_worker(self):
        self.assertFalse(self.request("RUN_ANY_COMMAND")["ok"])
        self.assertFalse(self.pidfile.exists())

    def test_unauthorized_origin_is_rejected(self):
        rejected = subprocess.run([str(HOST), "chrome-extension://" + "b" * 32 + "/"], capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(rejected.returncode, 2)
        self.assertEqual(rejected.stdout, b"")

    def test_oversized_message_terminates_connection(self):
        self.process.stdin.write(struct.pack("<I", 4_000_001))
        self.process.stdin.flush()
        self.assertEqual(self.process.wait(timeout=5), 3)
        self.assertFalse(self.pidfile.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)