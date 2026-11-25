"""Image download / type detection helpers."""

import base64
import mimetypes
import os
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

EXT_OK = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".tif", ".tiff", ".heic", ".avif"}


MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".avif": "image/avif",
}


def download(url, timeout=60):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 NotionExporter"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read(), resp.headers.get("Content-Type", "")


def detect_ext(url, ctype, data):
    ext = os.path.splitext(unquote(urlparse(url).path))[1].lower()
    if ext in EXT_OK:
        return ext
    if data[:8].startswith(b"\x89PNG"):
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"GIF8":
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if b"<svg" in data[:512]:
        return ".svg"
    return mimetypes.guess_extension((ctype or "").split(";")[0].strip()) or ".png"


def data_uri(img):
    """data: URI of an Asset (uses img.ext / img.bytes)."""
    mime = MIME.get(img.ext or ".png", "image/png")
    return f"data:{mime};base64," + base64.b64encode(img.bytes).decode()


def _load_custom_icon_data_uri(path: str) -> str:
    """Load a custom icon file and return as a data URI."""
    try:
        p = Path(path)
        if not p.exists():
            return ""
        raw = p.read_bytes()
        ext = p.suffix.lower()
        mime = MIME.get(ext, "image/png")
        return f"data:{mime};base64," + base64.b64encode(raw).decode()
    except Exception:
        return ""
