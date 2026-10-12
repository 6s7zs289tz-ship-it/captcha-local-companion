"""Release-only validation using a generated blank image and the bundled runtime."""
import io
import pathlib
import runpy
import sys
from unittest.mock import patch

root = pathlib.Path(sys.argv[1]).resolve()
runtime = root / "runtime"
for name in ("python.exe", "msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
    assert (runtime / name).is_file(), "missing bundled runtime file: " + name
assert pathlib.Path(sys.executable).resolve().parent == runtime, "check must use bundled Python"

from PIL import Image
import rapidocr_onnxruntime
model_root = pathlib.Path(rapidocr_onnxruntime.__file__).parent
assert len(list(model_root.rglob("*.onnx"))) >= 3, "offline OCR models missing"

image = Image.new("RGB", (96, 40), "white")
data = io.BytesIO()
image.save(data, format="PNG")
worker = runpy.run_path(str(root / "worker" / "ocr-server.py"))
engine = worker["RapidOcrEngine"]()
with patch("socket.socket.connect", side_effect=RuntimeError("offline check forbids network")), patch("socket.create_connection", side_effect=RuntimeError("offline check forbids network")):
    with worker["engine_output_to_stderr"]():
        text, confidence = engine.recognize(data.getvalue(), "")
assert isinstance(text, str) and 0 <= confidence <= 1
assert engine._client is not None, "recognition did not load bundled OCR model"
print("Bundled Python, CRT DLLs and offline OCR models passed a generated-image check.")