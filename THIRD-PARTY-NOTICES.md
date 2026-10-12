# Third-party notices

The companion's own source code is licensed under the MIT license in `LICENSE`.
Third-party software and model weights keep their respective licenses and copyright
notices. This inventory is a guide to the bundled components, not a replacement for
the original license texts.

## Runtime and OCR models

- **CPython 3.12.10**, Copyright Python Software Foundation and other contributors:
  [Python Software Foundation License Version 2 and incorporated-software notices](https://docs.python.org/3.12/license.html).
  The unmodified interpreter comes from the
  [official Windows x64 embeddable distribution](https://www.python.org/downloads/release/python-31210/).
  Its complete `runtime/LICENSE.txt` must remain in the installation package.
  Packaging changes only `python312._pth` to locate the bundled Python packages;
  this project does not modify the Python interpreter or standard-library source.
- **RapidOCR 1.4.4**, Copyright RapidOCR Authors:
  [Apache License 2.0](https://github.com/RapidAI/RapidOCR/blob/v1.4.4/LICENSE).
  The `rapidocr-onnxruntime` wheel includes the offline PP-OCR detection,
  direction-classification, and text-recognition ONNX models. The worker uses one
  OCR engine, limits CPU inference threads, and skips direction classification for
  CAPTCHA recognition. It does not download model files at runtime.
- The OCR model weights originate from **PaddleOCR**, Copyright Baidu and/or the
  relevant PaddleOCR rights holders. The upstream project uses
  [Apache License 2.0](https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE).
  Conversion to ONNX does not transfer model ownership to this companion. Preserve
  RapidOCR/PaddleOCR copyright notices and the Apache license text when packaging
  or redistributing these models. See the
  [RapidOCR model attribution](https://github.com/RapidAI/RapidOCR#license).

## Pinned Python packages

Versions correspond to `requirements.txt`. The linked PyPI pages and upstream
license files identify the original suppliers. Preserve the packages' bundled
`*.dist-info` license files, `LICENSE*`, `COPYING*`, `NOTICE*`, and embedded
third-party notices; do not strip them to reduce installer size.

| Package | Version | License and primary source |
| --- | --- | --- |
| rapidocr-onnxruntime | 1.4.4 | [Apache-2.0](https://pypi.org/project/rapidocr-onnxruntime/1.4.4/) |
| onnxruntime (CPU) | 1.20.1 | [MIT](https://pypi.org/project/onnxruntime/1.20.1/) |
| numpy | 2.2.6 | [BSD-3-Clause and bundled-library notices](https://pypi.org/project/numpy/2.2.6/) |
| opencv-python | 4.11.0.86 | [Apache-2.0 for OpenCV](https://pypi.org/project/opencv-python/4.11.0.86/); [MIT for Python packaging and bundled-library notices](https://github.com/opencv/opencv-python#licensing) |
| Pillow | 12.3.0 | [MIT-CMU](https://pypi.org/project/Pillow/12.3.0/) |
| pyclipper | 1.3.0.post6 | [MIT](https://pypi.org/project/pyclipper/1.3.0.post6/) |
| Shapely | 2.0.7 | [BSD-3-Clause](https://pypi.org/project/Shapely/2.0.7/) and bundled GEOS notices |
| PyYAML | 6.0.2 | [MIT](https://pypi.org/project/PyYAML/6.0.2/) |
| six | 1.17.0 | [MIT](https://pypi.org/project/six/1.17.0/) |
| tqdm | 4.67.1 | [MPL-2.0 AND MIT](https://pypi.org/project/tqdm/4.67.1/) |
| coloredlogs | 15.0.1 | [MIT](https://pypi.org/project/coloredlogs/15.0.1/) |
| humanfriendly | 10.0 | [MIT](https://pypi.org/project/humanfriendly/10.0/) |
| flatbuffers | 25.2.10 | [Apache-2.0](https://pypi.org/project/flatbuffers/25.2.10/) |
| packaging | 24.2 | [Apache-2.0 OR BSD](https://github.com/pypa/packaging/blob/24.2/LICENSE) |
| protobuf | 7.36.2 | [BSD-3-Clause](https://pypi.org/project/protobuf/7.36.2/) |
| sympy | 1.13.3 | [BSD](https://pypi.org/project/sympy/1.13.3/) |
| mpmath | 1.3.0 | [BSD](https://pypi.org/project/mpmath/1.3.0/) |
| colorama (Windows) | 0.4.6 | [BSD-3-Clause](https://github.com/tartley/colorama/blob/0.4.6/LICENSE.txt) |
| pyreadline3 (Windows) | 3.5.6 | [BSD](https://pypi.org/project/pyreadline3/3.5.6/) |

Binary wheels may contain additional native libraries. For example, OpenCV wheels
include FFmpeg under LGPL terms, Shapely wheels include GEOS under LGPL terms, and
NumPy wheels include numerical libraries with their own notices. The original
binary distribution's complete license and source-availability notices control
those components. See [OpenCV's licensing inventory](https://github.com/opencv/opencv-python#licensing)
and [Shapely's licensing section](https://github.com/shapely/shapely#licensing).
The companion does not modify those libraries; retain their source links, license
texts, and the ability to replace dynamically linked libraries as required by
those licenses.

## Microsoft Visual C++ runtime

The Windows release also contains Microsoft's app-local x64 Visual C++ runtime
DLLs from the Visual Studio 2022 VC143 redistributable directory. These are
Microsoft proprietary redistributable components, not code licensed under this
project's MIT license. Redistribution is subject to the applicable **Microsoft
Software License Terms** and the Visual Studio **Distributable Code / REDIST**
list. Only the permitted redistributable files may be included, from a licensed
Visual Studio build installation; do not copy arbitrary Windows system DLLs.

Primary sources:

- [Microsoft: Redistribute Visual C++ files](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files?view=msvc-170)
- [Microsoft Visual Studio license directory](https://visualstudio.microsoft.com/license-terms/)

The build copies these DLLs next to the bundled Python interpreter so users do not
need a separate administrator-level runtime installation. The DLLs and Microsoft's
applicable copyright/license notices retain their original terms. Releases must
be rebuilt when these bundled runtime components need security updates.
