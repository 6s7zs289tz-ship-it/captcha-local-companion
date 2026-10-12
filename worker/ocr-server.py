"""Stdio MCP worker for the optional local CAPTCHA companion.

Run with the companion's bundled Python: python -u worker/ocr-server.py.
The browser's native bridge owns this process; EOF releases its models and exits.
There is no HTTP listener, API key, network request, or Codex configuration.
RapidOCR and its bundled offline models load only on the first recognition call.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import io
import json
import math
import os
import re
import string
import sys
import warnings
from typing import Any, BinaryIO, Callable, TextIO

PROTOCOL_VERSION = "2025-06-18"
SERVER_VERSION = "0.1.2"
MAX_IMAGE_BYTES = 2_500_000
MAX_BASE64_CHARS = 4 * ((MAX_IMAGE_BYTES + 2) // 3)
MAX_MESSAGE_BYTES = MAX_BASE64_CHARS + 4096
MAX_IMAGE_PIXELS = 4_000_000
MAX_IMAGE_SIDE = 4096
MAX_TEXT_LENGTH = 64
DEFAULT_HINT_CHARS = string.ascii_uppercase + string.ascii_lowercase + string.digits
IMAGE_DATA_URL = re.compile(r"^data:image/(?:png|jpe?g|gif|webp|bmp);base64,", re.I)

TOOL = {
    "name": "recognize_captcha",
    "title": "Local CAPTCHA recognition",
    "description": "Recognize a user-selected CAPTCHA image locally with RapidOCR.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "imageBase64": {"type": "string", "minLength": 1, "maxLength": MAX_BASE64_CHARS + 64},
            "expectedLength": {"type": "integer", "minimum": 0, "maximum": MAX_TEXT_LENGTH},
            "hintChars": {"type": "string", "maxLength": 256},
            "requestId": {"type": "string", "maxLength": 128},
        },
        "required": ["imageBase64"],
        "additionalProperties": False,
    },
    "outputSchema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "maxLength": MAX_TEXT_LENGTH},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "engine": {"type": "string", "const": "rapidocr"},
            "requestId": {"type": "string", "maxLength": 128},
        },
        "required": ["text", "confidence", "engine", "requestId"],
        "additionalProperties": False,
    },
    "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
}


class ProtocolError(Exception):
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message


class ToolError(Exception):
    """Only fixed, safe user-facing messages belong in this exception."""


@contextlib.contextmanager
def engine_output_to_stderr():
    """Keep Python prints and native-library stdout away from the MCP pipe."""
    saved_fd = None
    try:
        sys.stdout.flush()
        try:
            stdout_fd = sys.stdout.fileno()
            stderr_fd = sys.stderr.fileno()
            saved_fd = os.dup(stdout_fd)
            os.dup2(stderr_fd, stdout_fd)
        except (AttributeError, OSError, io.UnsupportedOperation):
            if saved_fd is not None:
                os.close(saved_fd)
                saved_fd = None
        with contextlib.redirect_stdout(sys.stderr):
            yield
    finally:
        if saved_fd is not None:
            sys.stderr.flush()
            os.dup2(saved_fd, stdout_fd)
            os.close(saved_fd)


def normalize_rows(rows: Any, hint_chars: str) -> tuple[str, float]:
    if rows is None:
        return "", 0.0
    if not isinstance(rows, (list, tuple)):
        raise ToolError("本地识别返回了无效结果，请重试。")
    allowed = set(hint_chars or DEFAULT_HINT_CHARS)
    parts: list[str] = []
    scores: list[float] = []
    text_length = 0
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 3 or not isinstance(row[1], str):
            raise ToolError("本地识别返回了无效结果，请重试。")
        text = "".join(char for char in row[1] if char in allowed)
        if not text:
            continue
        text_length += len(text)
        if text_length > MAX_TEXT_LENGTH:
            raise ToolError("本地识别结果过长，请检查验证码图片。")
        parts.append(text)
        try:
            score = float(row[2])
        except (TypeError, ValueError, OverflowError):
            score = 0.0
        scores.append(max(0.0, min(1.0, score)) if math.isfinite(score) else 0.0)
    return "".join(parts), sum(scores) / len(scores) if scores else 0.0


class RapidOcrEngine:
    def __init__(self) -> None:
        self._client = None

    def recognize(self, image_data: bytes, hint_chars: str) -> tuple[str, float]:
        try:
            from PIL import Image

            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(image_data)) as image:
                    width, height = image.size
                    if not (0 < width <= MAX_IMAGE_SIDE and 0 < height <= MAX_IMAGE_SIDE):
                        raise ValueError("invalid image dimensions")
                    if width * height > MAX_IMAGE_PIXELS:
                        raise ValueError("too many pixels")
                    image.verify()
        except ImportError:
            raise ToolError("本地识别组件不完整，请在插件设置中重新安装。") from None
        except Exception:
            raise ToolError("图片数据无效或尺寸过大，请重新获取验证码。") from None

        if self._client is None:
            try:
                from rapidocr_onnxruntime import RapidOCR

                self._client = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1, print_verbose=False)
            except Exception:
                raise ToolError("本地识别组件无法加载，请在插件设置中重新安装。") from None
        try:
            rows, _ = self._client(image_data, use_cls=False)
            return normalize_rows(rows, hint_chars)
        except ToolError:
            raise
        except Exception:
            raise ToolError("本地识别失败，请重试或使用在线识别。") from None


def decode_image(value: str) -> bytes:
    encoded = IMAGE_DATA_URL.sub("", value, count=1)
    if not encoded or len(encoded) > MAX_BASE64_CHARS:
        raise ToolError("验证码图片超过 2.5 MB 或没有图片数据。")
    try:
        image_data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ToolError("图片编码无效，请重新获取验证码。") from None
    if not image_data or len(image_data) > MAX_IMAGE_BYTES:
        raise ToolError("验证码图片超过 2.5 MB 或没有图片数据。")
    return image_data


def validate_arguments(arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict) or set(arguments) - set(TOOL["inputSchema"]["properties"]):
        raise ProtocolError(-32602, "Invalid tool arguments.")
    image = arguments.get("imageBase64")
    if not isinstance(image, str) or not image or len(image) > MAX_BASE64_CHARS + 64:
        raise ProtocolError(-32602, "imageBase64 must be a non-empty, bounded string.")
    expected = arguments.get("expectedLength", 0)
    if type(expected) is not int or not 0 <= expected <= MAX_TEXT_LENGTH:
        raise ProtocolError(-32602, "expectedLength must be an integer from 0 to 64.")
    hint = arguments.get("hintChars", "")
    if not isinstance(hint, str) or len(hint) > 256:
        raise ProtocolError(-32602, "hintChars must be a string of at most 256 characters.")
    request_id = arguments.get("requestId", "")
    if not isinstance(request_id, str) or len(request_id) > 128:
        raise ProtocolError(-32602, "requestId must be a string of at most 128 characters.")
    return {"imageBase64": image, "expectedLength": expected, "hintChars": hint, "requestId": request_id}


class McpServer:
    def __init__(self, engine_factory: Callable[[], Any] = RapidOcrEngine) -> None:
        self._engine_factory = engine_factory
        self._engine = None
        self._initialized = False
        self._ready = False

    @staticmethod
    def error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def handle(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return self.error(None, -32600, "Invalid Request.")
        request_id = message.get("id")
        if "id" in message:
            if isinstance(request_id, bool) or not isinstance(request_id, (str, int, float, type(None))):
                return self.error(None, -32600, "Invalid Request.")
            if isinstance(request_id, float) and not math.isfinite(request_id):
                return self.error(None, -32600, "Invalid Request.")
        method = message["method"]
        params = message.get("params", {})
        if "id" not in message:
            if method == "notifications/initialized" and self._initialized and isinstance(params, dict):
                self._ready = True
            return None
        try:
            if not isinstance(params, dict):
                raise ProtocolError(-32602, "params must be an object.")
            if method == "ping":
                result = {}
            elif method == "initialize":
                result = self._initialize(params)
            elif method in ("tools/list", "tools/call"):
                if not self._ready:
                    raise ProtocolError(-32000, "Server is not initialized.")
                if method == "tools/list":
                    if params.get("cursor") is not None:
                        raise ProtocolError(-32602, "Unknown tools cursor.")
                    result = {"tools": [TOOL]}
                else:
                    result = self._call(params)
            else:
                raise ProtocolError(-32601, "Method not found.")
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except ProtocolError as error:
            return self.error(request_id, error.code, error.message)
        except Exception:
            return self.error(request_id, -32603, "Internal error.")

    def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        client = params.get("clientInfo")
        if not isinstance(params.get("protocolVersion"), str) or not params["protocolVersion"] or not isinstance(params.get("capabilities"), dict):
            raise ProtocolError(-32602, "Invalid initialization parameters.")
        if not isinstance(client, dict) or not all(isinstance(client.get(key), str) and client[key] for key in ("name", "version")):
            raise ProtocolError(-32602, "Invalid clientInfo.")
        if self._initialized:
            raise ProtocolError(-32600, "Server is already initialized.")
        self._initialized = True
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "captcha-local-ocr", "version": SERVER_VERSION},
        }

    def _call(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("name") != TOOL["name"]:
            raise ProtocolError(-32602, "Unknown tool.")
        arguments = validate_arguments(params.get("arguments", {}))
        try:
            image_data = decode_image(arguments["imageBase64"])
            with engine_output_to_stderr():
                if self._engine is None:
                    self._engine = self._engine_factory()
                text, confidence = self._engine.recognize(image_data, arguments["hintChars"])
            if not isinstance(text, str) or len(text) > MAX_TEXT_LENGTH:
                raise ToolError("本地识别返回了无效结果，请重试。")
            if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not math.isfinite(confidence):
                raise ToolError("本地识别返回了无效结果，请重试。")
            if not text:
                raise ToolError("本地服务未识别出文字，请重试或使用在线识别。")
            if arguments["expectedLength"] and len(text) != arguments["expectedLength"]:
                raise ToolError("本地识别结果的字符数量与预期不一致，请重试。")
            structured = {"text": text, "confidence": max(0.0, min(1.0, confidence)), "engine": "rapidocr", "requestId": arguments["requestId"]}
            return {
                "content": [{"type": "text", "text": json.dumps(structured, ensure_ascii=False, separators=(",", ":"))}],
                "structuredContent": structured,
                "isError": False,
            }
        except ToolError as error:
            return {"content": [{"type": "text", "text": str(error)}], "isError": True}
        except Exception:
            return {"content": [{"type": "text", "text": "本地识别失败，请重试或重新安装本地组件。"}], "isError": True}


def reject_json_constant(_value: str) -> None:
    raise ValueError("Invalid JSON constant")


def serve(reader: BinaryIO, writer: TextIO, engine_factory: Callable[[], Any] = RapidOcrEngine) -> None:
    server = McpServer(engine_factory)
    while True:
        line = reader.readline(MAX_MESSAGE_BYTES + 1)
        if not line:
            return
        if len(line) > MAX_MESSAGE_BYTES:
            while line and not line.endswith(b"\n"):
                line = reader.readline(MAX_MESSAGE_BYTES + 1)
            response = server.error(None, -32600, "Request exceeds the message size limit.")
        elif not line.strip():
            continue
        else:
            try:
                message = json.loads(line.decode("utf-8"), parse_constant=reject_json_constant)
            except (ValueError, UnicodeDecodeError, RecursionError):
                response = server.error(None, -32700, "Parse error.")
            else:
                response = server.handle(message)
        if response is not None:
            writer.write(json.dumps(response, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
            writer.flush()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        serve(sys.stdin.buffer, sys.stdout)
    except (BrokenPipeError, KeyboardInterrupt):
        return 0
    except Exception:
        sys.stderr.write("本地识别通信已结束，请重新连接本地组件。\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
