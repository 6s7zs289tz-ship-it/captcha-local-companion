"""Release-only checks with generated images and the pruned bundled runtime."""
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

from PIL import Image, ImageDraw, ImageFont
import cv2
import numpy as np
import rapidocr_onnxruntime

model_root = pathlib.Path(rapidocr_onnxruntime.__file__).parent
assert len(list(model_root.rglob("*.onnx"))) >= 3, "offline OCR models missing"
assert not list(pathlib.Path(cv2.__file__).parent.glob("opencv_videoio_ffmpeg*_64.dll")), "unused video plugin was not pruned"

image = Image.new("RGB", (420, 150), "white")
draw = ImageDraw.Draw(image)
draw.text((20, 20), "AB12", font=ImageFont.load_default(size=80), fill="black")
data = io.BytesIO()
image.save(data, format="PNG")
decoded = cv2.imdecode(np.frombuffer(data.getvalue(), dtype=np.uint8), cv2.IMREAD_COLOR)
assert decoded is not None and decoded.shape[:2] == (150, 420), "PNG decoding failed"
warped = cv2.warpPerspective(decoded, np.eye(3), (420, 150))
assert warped.shape == decoded.shape, "image perspective transform failed"

worker = runpy.run_path(str(root / "worker" / "ocr-server.py"))
engine = worker["RapidOcrEngine"]()
with patch("socket.socket.connect", side_effect=RuntimeError("offline check forbids network")), patch("socket.create_connection", side_effect=RuntimeError("offline check forbids network")):
    with worker["engine_output_to_stderr"]():
        text, confidence = engine.recognize(data.getvalue(), "")
assert text == "AB12", "generated high-contrast recognition did not return AB12"
assert 0 <= confidence <= 1 and engine._client is not None
print("Pruned bundled Python, CRT DLLs, image decoding/transform and offline AB12 recognition passed.")