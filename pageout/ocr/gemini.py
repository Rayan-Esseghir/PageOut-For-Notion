"""Gemini Vision Math OCR (whiteboard photos -> LaTeX)."""

import os
import re
import time
from typing import Any

try:
    from google import genai as _genai
    from google.genai import types as _genai_types

    _GENAI_AVAILABLE = True
except ImportError:
    _genai = None  # type: ignore[assignment]  # pip install google-genai
    _genai_types = None  # type: ignore[assignment]
    _GENAI_AVAILABLE = False

from pageout.core.assets import MIME, detect_ext, download
from pageout.core.ir import Asset, walk

WHITEBOARD_OCR_PROMPT = (
    "You are an expert mathematics professor and LaTeX typesetter. Transcribe all attached whiteboard images "
    "in sequence from Image 1 to Image N as one continuous, logically structured math lecture in clean LaTeX body code. "
    "Follow these rules strictly:\n"
    "1. Continuous Flow: Connect multi-board proofs, theorems, definitions, and equations smoothly across images "
    "without repeating headers, duplicating statements, or adding markdown code fences (```).\n"
    "2. Logical Order: Reconstruct the mathematical flow logically (follow columns from left-to-right and top-to-bottom, "
    "and trace arrows, side-boxes, and margin notes into their proper logical sequence as neatly formatted remarks).\n"
    "3. Clean Up Noise: Ignore crossed-out mistakes, stray marks, and eraser smudges. Fix ambiguous handwritten "
    "symbols using mathematical context (e.g., distinguish x vs \\times, 0 vs O, \\partial vs 2, \\in vs \\varepsilon).\n"
    "4. Structured Math Environments: Use standard amsmath/amsthm environments cleanly (align*, equation*, cases, "
    "pmatrix/bmatrix, \\textbf{Theorem:}, \\textbf{Definition:}, \\textbf{Proof:}, \\textbf{Example:}, \\textbf{Remark:}).\n"
    "5. Output Format: Return ONLY valid, compilable LaTeX body code. Do NOT include \\documentclass, \\begin{document}, "
    "\\end{document}, or markdown ``` fences."
)


def _generate_content_with_retry(client, model_name: str, contents: list, log_fn=None):
    """Executes generate_content with up to 3 retries (exponential backoff: 5s, 15s, 30s) on 429 or 503 errors.
    If the selected model still raises 503 UNAVAILABLE after retries, automatically falls back to gemini-3.5-flash-lite.
    Returns (response, model_used).
    """
    delays = [5, 15, 30]
    fallback_model = "gemini-3.5-flash-lite"

    def attempt_generate(model: str):
        for attempt in range(len(delays) + 1):
            try:
                return client.models.generate_content(model=model, contents=contents)
            except Exception as e:
                err_str = str(e).lower()
                code = getattr(e, "code", None)
                status = getattr(e, "status", None)
                status_code = getattr(e, "status_code", None)

                is_429 = "429" in err_str or "resource_exhausted" in err_str or 429 in (code, status, status_code)
                is_503 = "503" in err_str or "unavailable" in err_str or 503 in (code, status, status_code)

                if not (is_429 or is_503) or attempt >= len(delays):
                    raise

                wait_sec = delays[attempt]
                err_type = "429 RESOURCE_EXHAUSTED" if is_429 else "503 UNAVAILABLE"
                if log_fn:
                    log_fn(
                        f"  [Math OCR] {model} hit {err_type}. Retrying in {wait_sec}s (retry {attempt + 1}/{len(delays)})..."
                    )
                time.sleep(wait_sec)

    try:
        resp = attempt_generate(model_name)
        return resp, model_name
    except Exception as e:
        err_str = str(e).lower()
        code = getattr(e, "code", None)
        status = getattr(e, "status", None)
        status_code = getattr(e, "status_code", None)
        is_503 = "503" in err_str or "unavailable" in err_str or 503 in (code, status, status_code)

        if is_503 and model_name != fallback_model:
            if log_fn:
                log_fn(
                    f"  [Math OCR Fallback] {model_name} still unavailable (503). Falling back to {fallback_model}..."
                )
            resp = attempt_generate(fallback_model)
            return resp, fallback_model
        raise


def transcribe_whiteboard_images(
    images: list,
    api_key: str,
    model_name: str = "gemini-3.5-flash-lite",
    log_fn=None,
) -> tuple[str, str]:
    """Transcribes a list of whiteboard images into one continuous, logically structured math lecture
    in clean LaTeX body code using Gemini Vision.
    Images: list of dicts with keys {"bytes": bytes, "mime": str, "num": int}
    Returns (transcription_text, model_used).
    """
    if not _GENAI_AVAILABLE:
        raise Exception("The google-genai library is not installed. Install with: pip install google-genai")
    if not api_key:
        raise Exception("Gemini API key is required for Math OCR. Please enter your key in the LaTeX & OCR tab.")
    if not images:
        return "", model_name

    client = _genai.Client(api_key=api_key)

    chunk_size = 10
    chunks = [images[i : i + chunk_size] for i in range(0, len(images), chunk_size)]
    transcriptions = []
    used_model = model_name

    for c_idx, chunk in enumerate(chunks):
        if c_idx > 0:
            if log_fn:
                log_fn("  [Math OCR] Pausing 15s between image chunks to respect rate limits...")
            time.sleep(15)

        contents: list[Any] = [WHITEBOARD_OCR_PROMPT]
        for item in chunk:
            idx = item.get("num", 1)
            part = _genai_types.Part.from_bytes(data=item["bytes"], mime_type=item.get("mime") or "image/jpeg")
            contents.append(f"Image {idx}:")
            contents.append(part)

        if log_fn:
            chunk_desc = (
                f"Image {chunk[0].get('num', 1)}"
                if len(chunk) == 1
                else f"Images {chunk[0].get('num', 1)}-{chunk[-1].get('num', len(chunk))}"
            )
            log_fn(f"  [Math OCR] Transcribing {chunk_desc} ({len(chunk)} image(s)) with {used_model}...")

        response, chunk_model = _generate_content_with_retry(client, used_model, contents, log_fn=log_fn)
        used_model = chunk_model

        text = (response.text or "").strip()
        text = re.sub(r"^```(?:latex|tex)?\s*\n?", "", text, flags=re.I)
        text = re.sub(r"\n?```$", "", text)
        if text.strip():
            transcriptions.append(text.strip())

    return "\n\n".join(transcriptions), used_model


def transcribe_whiteboard_image(
    img_bytes: bytes, mime_type: str, api_key: str, model_name: str = "gemini-3.5-flash-lite", log_fn=None
) -> str:
    """Transcribes a math whiteboard image into clean LaTeX using Gemini Vision."""
    text, _ = transcribe_whiteboard_images(
        [{"bytes": img_bytes, "mime": mime_type, "num": 1}], api_key=api_key, model_name=model_name, log_fn=log_fn
    )
    return text


def collect_page_images(blocks):
    """Collect all image blocks (in order) with downloaded bytes and mime types."""
    entries = []
    for b in walk(blocks):
        if b.kind != "image" or not b.media or not b.media.url:
            continue
        m = b.media
        img = m.asset
        if img is None:
            img = m.asset = Asset(url=m.url, n=len(entries) + 1)
        data = img.bytes
        if not data and img.path and os.path.exists(img.path):
            try:
                with open(img.path, "rb") as f_in:
                    data = f_in.read()
            except Exception:
                pass
        if not data and img.url:
            try:
                data, ctype = download(img.url)
                img.bytes = data
                img.ext = detect_ext(img.url, ctype, data)
            except Exception:
                pass
        if data:
            ext = img.ext or ".png"
            entries.append(
                {"block": b, "img": img, "bytes": data, "mime": MIME.get(ext, "image/jpeg"), "num": len(entries) + 1}
            )
    return entries
