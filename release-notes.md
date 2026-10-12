Optional local OCR companion for 64-bit Windows 10/11.

Install from the extension's explicit local-recognition setup flow. Keep the small pairing JSON in Downloads, open this installer once, then return to the extension and connect.

Includes its own Python, CPU OCR engine and model files; no API key or separate Python installation is required. OCR runs only on request. The model process is released after about two minutes of inactivity, when local recognition is turned off, or when its browser connection closes. No service or startup item is installed.

Local recognition may perform substantially worse than an online service on complex CAPTCHA images and uses additional disk space and memory. This is a generic OCR engine; no private-site tuning or credentials are included.

The executable is not code-signed. Windows may display an unknown-publisher warning. Check the adjacent SHA-256 file against the download before opening it.
The image-only package excludes development test fixtures, caches, face-classifier data and the optional FFmpeg video plugin while retaining original licenses and all OCR models. Release checks exercise PNG decoding, perspective transformation and real recognition of a generated AB12 image offline.
