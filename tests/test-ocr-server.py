"""Mock-only protocol tests; no OCR packages, models, listeners, or downloads."""

from __future__ import annotations

import base64
import contextlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import Mock, patch

WORKER_PATH = Path(__file__).absolute().parents[1] / "worker" / "ocr-server.py"
spec = importlib.util.spec_from_file_location("captcha_ocr_worker", WORKER_PATH)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
IMAGE = base64.b64encode(b"mock-image-data").decode("ascii")


def request(method, params=None, request_id=1):
    value = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        value["params"] = params
    return value


def initialize(server, version=worker.PROTOCOL_VERSION):
    result = server.handle(request("initialize", {
        "protocolVersion": version,
        "capabilities": {},
        "clientInfo": {"name": "mock-bridge", "version": "1.0.0"},
    }))
    server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return result


def call(server, **arguments):
    payload = {"imageBase64": IMAGE, **arguments}
    return server.handle(request("tools/call", {"name": "recognize_captcha", "arguments": payload}))


def mock_server(text="aB12", confidence=0.8):
    engine = Mock()
    engine.recognize.return_value = (text, confidence)
    factory = Mock(return_value=engine)
    server = worker.McpServer(factory)
    initialize(server)
    return server, factory, engine


class ProtocolTests(unittest.TestCase):
    def test_initialize_and_tools_list_do_not_load_engine(self):
        server, factory, _ = mock_server()
        factory.assert_not_called()
        response = server.handle(request("tools/list"))
        tool = response["result"]["tools"][0]
        self.assertEqual(tool["name"], "recognize_captcha")
        self.assertEqual(tool["inputSchema"]["required"], ["imageBase64"])
        self.assertEqual(set(tool["inputSchema"]["properties"]), {"imageBase64", "expectedLength", "hintChars", "requestId"})
        self.assertEqual(set(tool["outputSchema"]["required"]), {"text", "confidence", "engine", "requestId"})
        factory.assert_not_called()

    def test_ping_works_before_initialize(self):
        factory = Mock()
        server = worker.McpServer(factory)
        self.assertEqual(server.handle(request("ping")), {"jsonrpc": "2.0", "id": 1, "result": {}})
        factory.assert_not_called()

    def test_tools_wait_for_initialized_notification(self):
        server = worker.McpServer(Mock())
        params = {"protocolVersion": worker.PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}
        self.assertEqual(server.handle(request("tools/list"))["error"]["code"], -32000)
        server.handle(request("initialize", params))
        self.assertEqual(server.handle(request("tools/list"))["error"]["code"], -32000)
        server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertIn("result", server.handle(request("tools/list")))

    def test_early_initialized_notification_cannot_skip_initialize(self):
        server = worker.McpServer(Mock())
        server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual(server.handle(request("tools/list"))["error"]["code"], -32000)

    def test_protocol_negotiation_returns_supported_version(self):
        server = worker.McpServer(Mock())
        response = initialize(server, "future-version")
        self.assertEqual(response["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(response["result"]["capabilities"], {"tools": {"listChanged": False}})

    def test_invalid_initialize_parameters(self):
        cases = [{}, {"protocolVersion": 1}, {"protocolVersion": "2025-06-18", "capabilities": {}},
                 {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": ""}}]
        for params in cases:
            with self.subTest(params=params):
                self.assertEqual(worker.McpServer(Mock()).handle(request("initialize", params))["error"]["code"], -32602)

    def test_second_initialize_is_rejected(self):
        server, _, _ = mock_server()
        self.assertEqual(initialize(server)["error"]["code"], -32600)

    def test_unknown_method_and_unknown_tool_are_protocol_errors(self):
        server, _, _ = mock_server()
        self.assertEqual(server.handle(request("execute_anything"))["error"]["code"], -32601)
        self.assertEqual(server.handle(request("tools/call", {"name": "other"}))["error"]["code"], -32602)

    def test_notifications_never_receive_response_or_run_tools(self):
        server, factory, _ = mock_server()
        self.assertIsNone(server.handle({"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "recognize_captcha", "arguments": {"imageBase64": IMAGE}}}))
        self.assertIsNone(server.handle({"jsonrpc": "2.0", "method": "notifications/cancelled"}))
        self.assertIsNone(server.handle({"jsonrpc": "2.0", "method": "unknown"}))
        factory.assert_not_called()

    def test_invalid_requests_have_standard_error(self):
        for value in [None, [], True, {}, {"jsonrpc": "1.0", "method": "ping"}, {"jsonrpc": "2.0", "method": 1},
                      {"jsonrpc": "2.0", "method": "ping", "id": []}, {"jsonrpc": "2.0", "method": "ping", "id": True}]:
            with self.subTest(value=value):
                response = worker.McpServer(Mock()).handle(value)
                self.assertEqual(response["error"]["code"], -32600)
                self.assertIsNone(response["id"])

    def test_params_must_be_object(self):
        self.assertEqual(worker.McpServer(Mock()).handle(request("ping", []))["error"]["code"], -32602)

    def test_request_id_is_preserved(self):
        for value in [None, 1, 1.5, "call-7"]:
            with self.subTest(value=value):
                self.assertEqual(worker.McpServer(Mock()).handle(request("ping", request_id=value))["id"], value)

    def test_unknown_cursor_is_rejected(self):
        server, _, _ = mock_server()
        self.assertEqual(server.handle(request("tools/list", {"cursor": "unexpected"}))["error"]["code"], -32602)


class RecognitionTests(unittest.TestCase):
    def test_success_has_structured_and_text_content(self):
        server, factory, engine = mock_server()
        result = call(server, expectedLength=4, hintChars="aB12", requestId="capture-7")["result"]
        expected = {"text": "aB12", "confidence": 0.8, "engine": "rapidocr", "requestId": "capture-7"}
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"], expected)
        self.assertEqual(json.loads(result["content"][0]["text"]), expected)
        factory.assert_called_once()
        engine.recognize.assert_called_once_with(b"mock-image-data", "aB12")

    def test_default_optional_fields_are_safe(self):
        server, _, _ = mock_server()
        self.assertEqual(call(server)["result"]["structuredContent"]["requestId"], "")

    def test_engine_is_loaded_only_once(self):
        server, factory, engine = mock_server()
        call(server)
        call(server)
        factory.assert_called_once()
        self.assertEqual(engine.recognize.call_count, 2)

    def test_data_url_prefix_is_decoded(self):
        server, _, engine = mock_server()
        self.assertFalse(call(server, imageBase64="data:image/png;base64," + IMAGE)["result"]["isError"])
        engine.recognize.assert_called_once_with(b"mock-image-data", "")

    def test_invalid_base64_does_not_load_engine(self):
        for image in ["%%%", "not-base64", "data:image/svg+xml;base64," + IMAGE, "aGVsbG8=\n", "data:image/png;base64,"]:
            with self.subTest(image=image):
                server, factory, _ = mock_server()
                self.assertTrue(call(server, imageBase64=image)["result"]["isError"])
                factory.assert_not_called()

    def test_argument_validation_prevents_invalid_fields(self):
        cases = [{"imageBase64": None}, {"imageBase64": ""}, {"imageBase64": 1}, {"expectedLength": True},
                 {"expectedLength": -1}, {"expectedLength": 65}, {"expectedLength": 4.0}, {"hintChars": None},
                 {"hintChars": "x" * 257}, {"requestId": 7}, {"requestId": "x" * 129}, {"apiKey": "mock-value"}]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                server, factory, _ = mock_server()
                self.assertEqual(call(server, **arguments)["error"]["code"], -32602)
                factory.assert_not_called()

    def test_argument_object_is_required(self):
        server, factory, _ = mock_server()
        for value in [None, [], "invalid"]:
            response = server.handle(request("tools/call", {"name": "recognize_captcha", "arguments": value}))
            self.assertEqual(response["error"]["code"], -32602)
        factory.assert_not_called()

    def test_decoded_image_limit_checks_padding_boundary(self):
        accepted = base64.b64encode(b"x" * worker.MAX_IMAGE_BYTES).decode("ascii")
        self.assertEqual(len(worker.decode_image(accepted)), worker.MAX_IMAGE_BYTES)
        rejected = base64.b64encode(b"x" * (worker.MAX_IMAGE_BYTES + 1)).decode("ascii")
        with self.assertRaises(worker.ToolError):
            worker.decode_image(rejected)

    def test_large_encoded_image_never_loads_engine(self):
        server, factory, _ = mock_server()
        encoded = "x" * (worker.MAX_BASE64_CHARS + 65)
        self.assertEqual(call(server, imageBase64=encoded)["error"]["code"], -32602)
        factory.assert_not_called()

    def test_expected_length_mismatch_is_a_tool_error(self):
        server, _, _ = mock_server()
        result = call(server, expectedLength=6)["result"]
        self.assertTrue(result["isError"])
        self.assertNotIn("structuredContent", result)

    def test_empty_result_is_a_tool_error(self):
        server, _, _ = mock_server(text="")
        self.assertTrue(call(server)["result"]["isError"])

    def test_confidence_is_clamped_but_non_finite_values_are_rejected(self):
        for confidence, expected in [(-0.5, 0.0), (1.5, 1.0)]:
            server, _, _ = mock_server(confidence=confidence)
            self.assertEqual(call(server)["result"]["structuredContent"]["confidence"], expected)
        for confidence in [math.nan, math.inf, "0.8", True]:
            server, _, _ = mock_server(confidence=confidence)
            self.assertTrue(call(server)["result"]["isError"])

    def test_unexpected_exception_never_leaks_details(self):
        server, _, engine = mock_server()
        engine.recognize.side_effect = RuntimeError("private-path / model-failure / mock-image-base64 / mock-key")
        response = json.dumps(call(server), ensure_ascii=False)
        for detail in ["private-path", "model-failure", "mock-image-base64", "mock-key"]:
            self.assertNotIn(detail, response)
        self.assertTrue(json.loads(response)["result"]["isError"])

    def test_factory_failure_can_retry_and_does_not_leak(self):
        server, factory, engine = mock_server()
        factory.side_effect = [RuntimeError("private-path"), engine]
        self.assertTrue(call(server)["result"]["isError"])
        self.assertFalse(call(server)["result"]["isError"])
        self.assertEqual(factory.call_count, 2)


class EngineAdapterTests(unittest.TestCase):
    def fake_modules(self, size=(120, 40), rows=None, verify_error=None):
        image = Mock()
        image.size = size
        image.__enter__ = Mock(return_value=image)
        image.__exit__ = Mock(return_value=False)
        image.verify.side_effect = verify_error
        pil = types.ModuleType("PIL")
        pil.Image = Mock()
        pil.Image.DecompressionBombWarning = type("MockBombWarning", (Warning,), {})
        pil.Image.open.return_value = image
        rapid = types.ModuleType("rapidocr_onnxruntime")
        client = Mock(return_value=(rows if rows is not None else [[[], "aB12", 0.8]], [0.1]))
        rapid.RapidOCR = Mock(return_value=client)
        return {"PIL": pil, "rapidocr_onnxruntime": rapid}, pil, rapid, image, client

    def test_adapter_defers_import_and_uses_verified_cpu_options(self):
        engine = worker.RapidOcrEngine()
        self.assertIsNone(engine._client)
        modules, _, rapid, _, client = self.fake_modules()
        with patch.dict(sys.modules, modules):
            self.assertEqual(engine.recognize(b"mock-image", ""), ("aB12", 0.8))
            engine.recognize(b"mock-image", "")
        rapid.RapidOCR.assert_called_once_with(intra_op_num_threads=1, inter_op_num_threads=1, print_verbose=False)
        client.assert_called_with(b"mock-image", use_cls=False)

    def test_invalid_or_large_image_does_not_load_models(self):
        for size, failure in [((4097, 1), None), ((2001, 2000), None), ((0, 0), None), ((120, 40), ValueError("private-path"))]:
            with self.subTest(size=size):
                modules, _, rapid, _, _ = self.fake_modules(size=size, verify_error=failure)
                with patch.dict(sys.modules, modules), self.assertRaises(worker.ToolError) as caught:
                    worker.RapidOcrEngine().recognize(b"mock-image", "")
                self.assertNotIn("private-path", str(caught.exception))
                rapid.RapidOCR.assert_not_called()

    def test_missing_model_error_is_safe(self):
        modules, _, rapid, _, _ = self.fake_modules()
        rapid.RapidOCR.side_effect = RuntimeError("private-path")
        with patch.dict(sys.modules, modules), self.assertRaises(worker.ToolError) as caught:
            worker.RapidOcrEngine().recognize(b"mock-image", "")
        self.assertNotIn("private-path", str(caught.exception))

    def test_normalization_preserves_order_and_filters_hint_chars(self):
        rows = [[[], " A中b!", 0.6], [[], "12", 1.0]]
        self.assertEqual(worker.normalize_rows(rows, ""), ("Ab12", 0.8))
        self.assertEqual(worker.normalize_rows(rows, "12"), ("12", 1.0))
        self.assertEqual(worker.normalize_rows(rows, "中!"), ("中!", 0.6))

    def test_normalization_handles_empty_and_invalid_scores(self):
        self.assertEqual(worker.normalize_rows(None, ""), ("", 0.0))
        self.assertEqual(worker.normalize_rows([], ""), ("", 0.0))
        self.assertEqual(worker.normalize_rows([[[], "a", "bad"], [[], "b", math.nan]], ""), ("ab", 0.0))

    def test_malformed_and_unbounded_ocr_results_are_rejected(self):
        for rows in [{}, [["bad"]], [[[], 7, 0.8]], [[[], "x" * 65, 0.8]]]:
            with self.subTest(rows=rows), self.assertRaises(worker.ToolError):
                worker.normalize_rows(rows, "")


class StdioTests(unittest.TestCase):
    def run_stream(self, lines):
        engine = Mock()
        engine.recognize.return_value = ("aB12", 0.8)
        factory = Mock(return_value=engine)
        output = io.StringIO()
        data = b"".join(line if isinstance(line, bytes) else (json.dumps(line) + "\n").encode("utf-8") for line in lines)
        worker.serve(io.BytesIO(data), output, factory)
        return [json.loads(line) for line in output.getvalue().splitlines()], factory

    def test_eof_terminates_without_loading_model(self):
        responses, factory = self.run_stream([])
        self.assertEqual(responses, [])
        factory.assert_not_called()

    def test_parse_error_then_ping_recovers(self):
        responses, factory = self.run_stream([b"{broken\n", request("ping")])
        self.assertEqual(responses[0]["error"]["code"], -32700)
        self.assertEqual(responses[1]["result"], {})
        factory.assert_not_called()

    def test_utf8_errors_and_non_json_constants_are_rejected(self):
        for data in [b"\xff\n", b'{"jsonrpc":"2.0","id":NaN,"method":"ping"}\n']:
            with self.subTest(data=data):
                responses, _ = self.run_stream([data])
                self.assertEqual(responses[0]["error"]["code"], -32700)

    def test_oversize_line_is_drained_before_next_request(self):
        responses, factory = self.run_stream([b"x" * (worker.MAX_MESSAGE_BYTES * 2) + b"\n", request("ping")])
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]["error"]["code"], -32600)
        self.assertEqual(responses[1]["result"], {})
        factory.assert_not_called()

    def test_blank_lines_are_ignored(self):
        responses, _ = self.run_stream([b"\n \r\n", request("ping")])
        self.assertEqual(len(responses), 1)

    def test_engine_prints_are_redirected(self):
        server, _, engine = mock_server()
        def recognize(_image, _hint):
            print("mock-engine-log")
            return "aB12", 0.8
        engine.recognize.side_effect = recognize
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            response = call(server)
        self.assertFalse(response["result"]["isError"])
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "mock-engine-log\n")

    def test_native_stdout_is_redirected_with_a_mock_subprocess(self):
        harness = '''import importlib.util, os, sys
spec = importlib.util.spec_from_file_location("mock_worker", sys.argv[1])
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
class FakeEngine:
    def recognize(self, image, hint):
        print("mock-python-log", flush=True)
        os.write(1, b"mock-native-log\\n")
        return "aB12", 0.8
w.serve(sys.stdin.buffer, sys.stdout, FakeEngine)
'''
        messages = [request("initialize", {"protocolVersion": worker.PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {"name": "mock", "version": "1"}}),
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    request("tools/call", {"name": "recognize_captcha", "arguments": {"imageBase64": IMAGE}})]
        payload = "".join(json.dumps(item) + "\n" for item in messages).encode("utf-8")
        process = subprocess.run([sys.executable, "-B", "-u", "-c", harness, str(WORKER_PATH)], input=payload, capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", errors="replace"))
        responses = [json.loads(line) for line in process.stdout.decode("utf-8").splitlines()]
        self.assertEqual(len(responses), 2)
        self.assertFalse(responses[1]["result"]["isError"])
        self.assertIn(b"mock-python-log", process.stderr)
        self.assertIn(b"mock-native-log", process.stderr)


if __name__ == "__main__":
    unittest.main()
