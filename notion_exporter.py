"""
PageOut for Notion  –  1.0.0-beta.1  (BETA)

Install:
    pip install notion-client playwright pypdf python-docx pillow google-genai
    playwright install chromium

Exports Notion pages (from a database or single pages) to PDF, HTML,
Markdown, Text, Word, JSON and LaTeX (.tex), and can save the images
with custom names.
Two PDF engines: API (fast, no login, built from the page data) and
Browser (prints the real Notion page).

New in v5:
  - LaTeX (.tex) export with full compilable document wrapper
  - Gemini Vision Math OCR: converts whiteboard/handwritten images to LaTeX
    (requires a personal Gemini API key from https://aistudio.google.com/)
  - Per-user API key stored only in ~/.notion_pdf_exporter/config.json
  - Option to keep original whiteboard image below transcribed LaTeX
  - "Copy LaTeX" button after export completes
  - Smart whiteboard prompt: handles crowded boards, arrows, side-boxes,
    crossed-out mistakes, amsmath/amsthm environments
"""
import os
import re
import io
import sys
import json
import time
import queue
import shutil
import base64
import tempfile
import threading
import subprocess
import webbrowser
import mimetypes
import html as _html
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, unquote, quote
from urllib.request import Request, urlopen

from notion_client import Client
from playwright.sync_api import sync_playwright

try:
    from pypdf import PdfWriter as PdfMerger          # pip install pypdf (recommended)
except ImportError:
    from PyPDF2 import PdfMerger                      # fallback

try:
    import tkinter as tk
    from tkinter import messagebox, filedialog, ttk, colorchooser
    import tkinter.font as tkfont
except ImportError:                                   # headless use / tests
    tk = None

try:
    from google import genai as _genai
    from google.genai import types as _genai_types
    _GENAI_AVAILABLE = True
except ImportError:
    _genai = None                                     # pip install google-genai
    _genai_types = None
    _GENAI_AVAILABLE = False


# ----------------------------------------------------------------------
# PyInstaller-safe resource path
# ----------------------------------------------------------------------
def _resource_dir() -> Path:
    """Return the directory where bundled resources live (or the script dir)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


RESOURCE_DIR = _resource_dir()
APP_NAME     = "PageOut for Notion"
APP_VERSION  = "1.0.0-beta.1"
APP_STAGE    = "BETA"
CONFIG_VERSION = 2


def _setup_portable_browsers():
    """Frozen .exe: use a 'browsers' folder next to the exe as Playwright's Chromium location."""
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        for name in ("browsers", "ms-playwright"):
            cand = exe_dir / name
            if cand.is_dir():
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(cand)
                return


def _windows_integration():
    """Sharp UI on HiDPI screens + own taskbar identity (so the custom icon shows)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PageOut.ForNotion.App")
    except Exception:
        pass


_setup_portable_browsers()


def resource_path(rel: str) -> Path:
    """Resolve a resource path that works both as .py and compiled .exe."""
    return RESOURCE_DIR / rel


# ----------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------
CONFIG_DIR  = os.path.join(os.path.expanduser("~"), ".notion_pdf_exporter")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
PROFILE_DIR = os.path.join(CONFIG_DIR, "browser_profile")   # saved Notion login

LINK_MODES   = ["Keep all links", "Remove all links", "Remove only Notion-internal links"]
OUTPUT_MODES = ["Merged + individual files", "Merged file only", "Individual files only"]
PAGE_SIZES   = ["A3", "A4", "A5", "Letter", "Legal", "Tabloid"]
SORT_BUILTIN = ["Date", "Title", "Created", "Last edited", "Database order"]
SOURCE_TYPES = ["Auto-detect", "Database", "Single page"]
ENGINES      = ["API (fast, no login needed)", "Browser (exact Notion look)"]
SUB_MODES    = ["Skip", "Inline in parent", "Separate files"]
IMG_MODES    = ["Embed in file", "Save locally & link", "Keep Notion link"]
ICON_MODES   = ["Show page icon", "Hide icon", "Custom icon file"]
PROP_LAYOUTS = ["Notion Table", "Inline Pills", "Minimalist List", "Hidden"]
FONT_FAMILIES= ["Sans-serif", "Serif", "Monospace"]
TEXT_ALIGNS  = ["Left", "Justify"]
HEAD_ALIGNS  = ["Left", "Center"]
DATE_PRESETS = [
    "YYYY-MM-DD", "DD/MM/YYYY", "MM/DD/YYYY",
    "MMM DD, YYYY", "MMMM D, YYYY",
    "D MMM YYYY", "ISO 8601", "Relative",
]
PAGENUM_POS  = ["Bottom Center", "Bottom Right", "Top Right"]
PAGENUM_FMT  = ["Page X of Y", "X"]
CAPTION_FMTS = ["{name}", "{name}.{ext}", "Figure {n}: {name}", "{original}", "{caption}"]

NAME_PRESETS = ["{date} - {title}", "{title}", "{index} - {title}",
                "{date:%Y-%m-%d} {title:60}", "{created} - {title}"]
IMG_PRESETS  = ["{page}_{n}", "{title} - {n}", "{date} - {title} - {n}",
                "{page}_{n} - {caption}", "{original}"]

LATEX_IMAGES_AS_COMMENTS = True     # images in .tex become "% [Image ...]" comments (for now)

# (name, category, is_google_font)   category: sans | serif | mono | arabic
FONT_CATALOG = [
    ("Segoe UI", "sans", False), ("Arial", "sans", False), ("Calibri", "sans", False),
    ("Verdana", "sans", False), ("Tahoma", "sans", False), ("Trebuchet MS", "sans", False),
    ("Century Gothic", "sans", False),
    ("Inter", "sans", True), ("Roboto", "sans", True), ("Open Sans", "sans", True),
    ("Lato", "sans", True), ("Poppins", "sans", True), ("Nunito", "sans", True),
    ("Montserrat", "sans", True), ("Source Sans 3", "sans", True), ("IBM Plex Sans", "sans", True),
    ("Georgia", "serif", False), ("Times New Roman", "serif", False), ("Cambria", "serif", False),
    ("Palatino Linotype", "serif", False), ("Garamond", "serif", False), ("Book Antiqua", "serif", False),
    ("Merriweather", "serif", True), ("Lora", "serif", True), ("Playfair Display", "serif", True),
    ("Source Serif 4", "serif", True), ("Crimson Pro", "serif", True), ("EB Garamond", "serif", True),
    ("Libre Baskerville", "serif", True),
    ("Consolas", "mono", False), ("Cascadia Code", "mono", False), ("Courier New", "mono", False),
    ("Fira Code", "mono", True), ("JetBrains Mono", "mono", True), ("Source Code Pro", "mono", True),
    ("IBM Plex Mono", "mono", True),
    ("Cairo", "arabic", True), ("Tajawal", "arabic", True), ("Amiri", "arabic", True),
    ("Noto Naskh Arabic", "arabic", True), ("Noto Sans Arabic", "arabic", True),
    ("IBM Plex Sans Arabic", "arabic", True), ("Almarai", "arabic", True),
    ("Scheherazade New", "arabic", True),
]
FONT_CATEGORY = {n: c for n, c, _ in FONT_CATALOG}
GOOGLE_FONTS  = {n for n, _, g in FONT_CATALOG if g}
SAME_AS_BODY  = "Same as body"

STYLE_PRESETS = {
    "Notion Classic": dict(font_family="Sans-serif", heading_font=SAME_AS_BODY, base_font_size=16,
                           line_spacing=1.5, text_align="Left", heading_align="Left",
                           title_separator=False, accent_color="#37352f", web_fonts=False),
    "Modern Blue":    dict(font_family="Inter", heading_font=SAME_AS_BODY, base_font_size=16,
                           line_spacing=1.65, text_align="Left", heading_align="Left",
                           title_separator=True, accent_color="#2563eb", web_fonts=True),
    "Academic Serif": dict(font_family="Cambria", heading_font=SAME_AS_BODY, base_font_size=15,
                           line_spacing=1.7, text_align="Justify", heading_align="Left",
                           title_separator=True, accent_color="#1f2937", web_fonts=False),
    "Elegant":        dict(font_family="Lora", heading_font="Playfair Display", base_font_size=16,
                           line_spacing=1.7, text_align="Left", heading_align="Left",
                           title_separator=True, accent_color="#9a3412", web_fonts=True),
    "Clean Report":   dict(font_family="Calibri", heading_font=SAME_AS_BODY, base_font_size=15,
                           line_spacing=1.55, text_align="Left", heading_align="Center",
                           title_separator=True, accent_color="#0f766e", web_fonts=False),
    "Developer Mono": dict(font_family="Consolas", heading_font=SAME_AS_BODY, base_font_size=14,
                           line_spacing=1.6, text_align="Left", heading_align="Left",
                           title_separator=False, accent_color="#374151", web_fonts=False),
    "Arabic (Cairo)": dict(font_family="Cairo", heading_font=SAME_AS_BODY, base_font_size=16,
                           line_spacing=1.85, text_align="Left", heading_align="Left",
                           title_separator=True, accent_color="#0f766e", web_fonts=True),
}

FORMATS      = ["pdf", "html", "md", "txt", "docx", "json", "tex"]
FORMAT_LABELS= {"pdf": "PDF", "html": "HTML", "md": "Markdown", "txt": "Text",
                "docx": "Word", "json": "JSON", "tex": "LaTeX (.tex)", "images": "Images"}
FOLDERS      = {"pdf": "PDF", "html": "HTML", "md": "Markdown", "txt": "Text",
                "docx": "Word", "json": "JSON", "tex": "LaTeX"}
EXTS         = {"pdf": ".pdf", "html": ".html", "md": ".md", "txt": ".txt",
                "docx": ".docx", "json": ".json", "tex": ".tex"}

GEMINI_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
]

DEFAULTS = {
    # source
    "token": "", "remember_token": False, "database": "", "source_type": SOURCE_TYPES[0],
    "use_login": True,
    # pages
    "name_format": "{date} - {title}", "sort_by": "Date", "sort_desc": False,
    "filter_prop": "", "filter_op": "contains", "filter_value": "", "max_pages": 0,
    # formats
    "fmt_pdf": True, "fmt_html": False, "fmt_md": False, "fmt_txt": False,
    "fmt_docx": False, "fmt_json": False, "fmt_tex": False, "fmt_images": False,
    "engine": ENGINES[0], "sub_mode": SUB_MODES[0], "sub_depth": 3, "sub_dbs": False,
    "combine": False,
    # Gemini Math OCR
    "gemini_api_key": "",
    "gemini_math_ocr": False,
    "gemini_model": "gemini-3.5-flash-lite",
    "keep_whiteboard_image": False,
    # images
    "img_handling": IMG_MODES[0], "img_format": "{page}_{n}", "img_subfolder": True,
    "img_cover": False,
    # image layout (new)
    "maximize_images": False, "one_image_per_page": False,
    "show_image_names": False, "caption_format": "{name}",
    # content
    "expand_toggles": True, "light_theme": True, "clean_layout": True,
    "links": LINK_MODES[0], "custom_css": "",
    # pdf
    "page_size": "A4", "orientation": "Portrait", "margin_mm": 20, "scale": 100,
    "print_background": True, "page_numbers": False,
    "page_num_position": PAGENUM_POS[0], "page_num_format": PAGENUM_FMT[0],
    # output
    "save_dir": "", "output_mode": OUTPUT_MODES[0], "merged_name": "All_Pages",
    "bookmarks": True, "skip_existing": False, "extra_wait": 2.0, "retries": 1,
    # styling (new)
    "font_family": FONT_FAMILIES[0],
    "base_font_size": 16,
    "line_spacing": 1.5,
    "remove_blank_pages": True,
    "text_align": TEXT_ALIGNS[0],
    "heading_align": HEAD_ALIGNS[0],
    "title_separator": False,
    "date_format_props": "YYYY-MM-DD",
    # page icon (new)
    "icon_mode": ICON_MODES[0],
    "icon_custom_file": "",
    # cover page (new)
    "cover_page": False,
    # property layout (new)
    "prop_layout": PROP_LAYOUTS[0],
    # v5.1: design / speed
    "theme_preset": "Notion Classic",
    "heading_font": SAME_AS_BODY,
    "accent_color": "#37352f",
    "web_fonts": False,
    "render_math": True,
    "workers": 4,
    "optimize_images": True,
    "image_max_px": 1600,
}


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    if int(cfg.get("_ver", 0)) < CONFIG_VERSION:      # new, more comfortable defaults
        cfg["margin_mm"]    = DEFAULTS["margin_mm"]
        cfg["line_spacing"] = DEFAULTS["line_spacing"]
        cfg["_ver"]         = CONFIG_VERSION
    if not cfg.get("token"):
        cfg["token"] = os.environ.get("NOTION_TOKEN", "")
    if not cfg.get("gemini_api_key"):
        cfg["gemini_api_key"] = os.environ.get("GEMINI_API_KEY", "")
    return cfg


def save_config(cfg):
    data = dict(cfg)
    data["_ver"] = CONFIG_VERSION
    if not data.get("remember_token"):
        data["token"] = ""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


# ----------------------------------------------------------------------
# App icon (custom + programmatic fallback)
# ----------------------------------------------------------------------
def _make_programmatic_icon():
    """Generate a small Notion-style 'N' icon as a PhotoImage (Tkinter)."""
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageTk
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Rounded square background
        margin = 4
        draw.rounded_rectangle([margin, margin, size - margin, size - margin],
                                radius=12, fill="#000000")
        # White "N"
        try:
            font = ImageFont.truetype("arial.ttf", 38)
        except Exception:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), "N", font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]),
                  "N", fill="white", font=font)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None


def apply_icon(root):
    """
    Set the window icon.  Search order:
      1. icon.ico  (best on Windows – supports multi-res)
      2. icon.png  (cross-platform)
      3. icon.jpg  (project has this)
      4. Programmatic PIL icon
      5. No icon (silent fallback)
    """
    base = resource_path("icon")
    for ext in (".ico", ".png", ".jpg", ".jpeg"):
        p = base.with_suffix(ext)
        if p.exists():
            try:
                if ext == ".ico":
                    root.iconbitmap(str(p))
                    return
                else:
                    from PIL import Image, ImageTk
                    img = Image.open(str(p)).resize((64, 64), Image.LANCZOS)
                    ph  = ImageTk.PhotoImage(img)
                    root.iconphoto(True, ph)
                    root._icon_ref = ph   # keep reference
                    return
            except Exception:
                continue
    # Programmatic fallback
    ph = _make_programmatic_icon()
    if ph:
        root.iconphoto(True, ph)
        root._icon_ref = ph


# ----------------------------------------------------------------------
# Date formatting helpers
# ----------------------------------------------------------------------
_DATE_FMT_MAP = {
    "YYYY-MM-DD":    "%Y-%m-%d",
    "DD/MM/YYYY":    "%d/%m/%Y",
    "MM/DD/YYYY":    "%m/%d/%Y",
    "MMM DD, YYYY":  "%b %d, %Y",
    "MMMM D, YYYY":  "%B %-d, %Y" if sys.platform != "win32" else "%B %#d, %Y",
    "D MMM YYYY":    "%-d %b %Y"  if sys.platform != "win32" else "%#d %b %Y",
    "ISO 8601":      "%Y-%m-%dT%H:%M:%SZ",
    "Relative":      None,   # handled specially
}


def format_date(iso_str: str, fmt_preset: str) -> str:
    """Format an ISO date string using the given preset or strftime pattern."""
    if not iso_str:
        return ""
    # Relative
    if fmt_preset == "Relative":
        try:
            d = datetime.fromisoformat(iso_str[:10])
            delta = (datetime.now() - d).days
            if delta == 0:
                return "Today"
            if delta == 1:
                return "Yesterday"
            if delta < 0:
                return f"In {-delta} days"
            if delta < 30:
                return f"{delta} days ago"
            if delta < 365:
                return f"{delta // 30} months ago"
            return f"{delta // 365} years ago"
        except Exception:
            return iso_str[:10]
    strfmt = _DATE_FMT_MAP.get(fmt_preset, fmt_preset)
    if strfmt is None:
        return iso_str[:10]
    try:
        return datetime.fromisoformat(iso_str[:10]).strftime(strfmt)
    except Exception:
        return iso_str[:10]


# ----------------------------------------------------------------------
# Notion helpers
# ----------------------------------------------------------------------
_API_SEM = threading.Semaphore(3)      # Notion allows ~3 requests/second on average


def set_api_concurrency(n):
    global _API_SEM
    _API_SEM = threading.Semaphore(max(1, int(n)))


def api(fn, **kw):
    """Call the Notion API, retrying on rate limits / temporary errors (thread-safe)."""
    for attempt in range(7):
        try:
            with _API_SEM:
                return fn(**kw)
        except Exception as e:
            s = str(e).lower()
            temp = any(x in s for x in ("429", "rate limit", "rate_limited", "timed out",
                                        "502", "503", "504", "bad gateway"))
            if attempt < 6 and temp:
                wait = 1.5 * (attempt + 1)
                try:
                    wait = max(wait, float(getattr(e, "headers", {}).get("retry-after")))
                except Exception:
                    pass
                time.sleep(wait)
                continue
            raise


def parse_database_id(text):
    """Accepts a raw ID or a full Notion URL (page or database)."""
    text = text.strip()
    path = urlparse(text).path if ("://" in text or "notion.so" in text) else text
    seg  = path.rstrip("/").rsplit("/", 1)[-1].replace("-", "")
    m    = re.search(r"([0-9a-fA-F]{32})$", seg)
    return m.group(1) if m else text


def clean_filename(name):
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return re.sub(r"\s+", " ", name).strip()


def extract_date_from_props(properties):
    """Return the first filled date property as YYYY-MM-DD ('' if none)."""
    dates = (p["date"]["start"] for p in properties.values()
             if p.get("type") == "date" and p.get("date"))
    return next(dates, "")[:10]


def plain(rts):
    return "".join(r.get("plain_text", "") for r in rts or [])


def prop_to_text(prop, date_fmt="YYYY-MM-DD"):
    t = prop.get("type")
    v = prop.get(t)
    if v is None:
        return ""
    if t in ("title", "rich_text"):
        return plain(v)
    if t == "date":
        raw = (v.get("start") or "")[:10]
        return format_date(raw, date_fmt) if raw else ""
    if t in ("select", "status"):
        return v.get("name", "")
    if t == "multi_select":
        return ", ".join(x.get("name", "") for x in v)
    if t in ("people",):
        return ", ".join(x.get("name") or "" for x in v)
    if t in ("created_by", "last_edited_by"):
        return v.get("name") or ""
    if t == "checkbox":
        return "Yes" if v else "No"
    if t in ("created_time", "last_edited_time"):
        return format_date(str(v)[:10], date_fmt)
    if t in ("number", "url", "email", "phone_number"):
        return str(v)
    if t == "files":
        return ", ".join(x.get("name", "") for x in v)
    if t == "unique_id":
        return f"{v.get('prefix') or ''}{'-' if v.get('prefix') else ''}{v.get('number', '')}"
    if t == "formula":
        ft = v.get("type")
        fv = v.get(ft)
        if isinstance(fv, dict):
            fv = fv.get("start")
        if fv is None:
            return ""
        if ft == "date":
            return format_date(str(fv)[:10], date_fmt)
        return str(fv)
    return ""


def page_title(page):
    return next((prop_to_text(v) for v in page["properties"].values()
                 if v["type"] == "title"), "") or "Untitled"


def page_fields(page, index=0, pad=3):
    props = page["properties"]
    f = {
        "title":   page_title(page),
        "date":    extract_date_from_props(props),
        "created": page.get("created_time", "")[:10],
        "edited":  page.get("last_edited_time", "")[:10],
        "parent":  "",
    }
    for k, v in props.items():
        txt = prop_to_text(v)
        if txt or k.lower() not in f:
            f[k.lower()] = txt
    f["index"] = f"{index:0{pad}d}"
    return f


def apply_fmt(value, fmt):
    if not fmt:
        return value
    if fmt.isdigit():
        return value[:int(fmt)]
    try:
        return datetime.fromisoformat(value[:10]).strftime(fmt)
    except Exception:
        return value


def build_name(template, fields):
    """{title} {date} {index} {created} {edited} {parent} {any property}.
    Extras: {date:%d-%m-%Y} formats dates, {title:40} truncates."""
    def repl(m):
        raw = m.group(1).strip()
        if raw.lower() in fields:
            return str(fields[raw.lower()])
        key, _, fmt = raw.partition(":")
        return apply_fmt(str(fields.get(key.strip().lower(), "")), fmt.strip())

    name = re.sub(r"\{([^{}]+)\}", repl, template)
    name = clean_filename(name)
    name = re.sub(r"(?:\s-)(?:\s-)+\s", " - ", name)
    name = re.sub(r"^[\s\-_.,]+|[\s\-_.,]+$", "", name)
    return (name or "Untitled")[:150].strip()


def passes_filter(page, prop, op, value):
    if not prop or not value:
        return True
    text = page_fields(page).get(prop.strip().lower(), "").lower()
    v    = value.strip().lower()
    if op == "contains":
        return v in text
    if op == "does not contain":
        return v not in text
    return text == v


def sort_pages(pages, by, desc):
    if by == "Database order":
        return list(reversed(pages)) if desc else list(pages)
    k = by.strip().lower()

    def key(p):
        f = page_fields(p)
        if k == "last edited":
            return f["edited"]
        return f.get(k, "").lower()

    return sorted(pages, key=key, reverse=desc)


def query_all(notion, database_id, limit=None):
    """Fetch rows of a database; works with the classic and newer data-source API."""
    def paginate(fn, **base):
        out, cursor = [], None
        while True:
            size = min(100, limit - len(out)) if limit else 100
            kw   = dict(base, page_size=size)
            if cursor:
                kw["start_cursor"] = cursor
            resp = api(fn, **kw)
            out.extend(resp.get("results", []))
            if (limit and len(out) >= limit) or not resp.get("has_more"):
                return out[:limit] if limit else out
            cursor = resp.get("next_cursor")

    try:
        return paginate(notion.databases.query, database_id=database_id)
    except Exception as first:
        ds_api = getattr(notion, "data_sources", None)
        if ds_api is None:
            raise Exception("Could not access the database. " + str(first))
        try:
            db      = api(notion.databases.retrieve, database_id=database_id)
            sources = db.get("data_sources") or []
            if not sources:
                raise first
            return paginate(ds_api.query, data_source_id=sources[0]["id"])
        except Exception:
            raise Exception("Could not access the database. " + str(first))


def resolve_roots(notion, source_text, source_type):
    """Turn IDs/URLs (space or comma separated) into page objects."""
    tokens = [t for t in re.split(r"[\s,;]+", source_text.strip()) if t]
    if not tokens:
        raise Exception("Enter a database or page ID / URL.")
    roots, seen = [], set()
    for tok in tokens:
        _id = parse_database_id(tok)
        got = None
        if source_type in ("Auto-detect", "Single page"):
            try:
                got = [api(notion.pages.retrieve, page_id=_id)]
            except Exception as e:
                if source_type == "Single page":
                    raise Exception("Could not open the page. " + str(e))
        if got is None:
            got = query_all(notion, _id)
        for p in got:
            if p["id"] not in seen:
                seen.add(p["id"])
                roots.append(p)
    return roots


def load_property_names(notion, source_text, source_type):
    tok = re.split(r"[\s,;]+", source_text.strip())[0]
    _id = parse_database_id(tok)
    if source_type in ("Auto-detect", "Single page"):
        try:
            return list(api(notion.pages.retrieve, page_id=_id)["properties"].keys())
        except Exception:
            if source_type == "Single page":
                raise
    try:
        db = api(notion.databases.retrieve, database_id=_id)
        if db.get("properties"):
            return list(db["properties"].keys())
    except Exception:
        pass
    pages = query_all(notion, _id, limit=1)
    if not pages:
        raise Exception("The database is empty or not shared with your integration.")
    return list(pages[0]["properties"].keys())


# ----------------------------------------------------------------------
# Block tree
# ----------------------------------------------------------------------
LIST_TYPES = ("bulleted_list_item", "numbered_list_item", "to_do")


def build_tree(notion, block_id, cache):
    """Fetch all blocks of a page/block recursively (sub-pages are not entered)."""
    if block_id in cache:
        return cache[block_id]
    out, cursor = [], None
    while True:
        kw = {"block_id": block_id, "page_size": 100}
        if cursor:
            kw["start_cursor"] = cursor
        resp = api(notion.blocks.children.list, **kw)
        out.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    for b in out:
        t = b["type"]
        if t in ("child_page", "child_database") or not b.get("has_children"):
            continue
        cid = b["id"]
        if t == "synced_block":
            cid = ((b["synced_block"].get("synced_from") or {}).get("block_id")) or cid
        try:
            b["children"] = build_tree(notion, cid, cache)
        except Exception:
            b["children"] = []
    cache[block_id] = out
    return out


def walk(blocks, subs=True):
    for b in blocks:
        yield b
        yield from walk(b.get("children", []), subs)
        if subs and b.get("_sub"):
            yield from walk(b["_sub"]["tree"], subs)


def attach_inline(notion, blocks, cache, depth, maxdepth):
    """Load sub-pages found inside `blocks` so they render inside the parent."""
    for b in list(walk(blocks, subs=False)):
        if b["type"] == "child_page" and depth <= maxdepth:
            try:
                tree = build_tree(notion, b["id"], cache)
            except Exception:
                continue
            b["_sub"] = {"title": b["child_page"].get("title") or "Untitled", "tree": tree}
            attach_inline(notion, tree, cache, depth + 1, maxdepth)


def strip_private(obj):
    if isinstance(obj, dict):
        return {k: strip_private(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [strip_private(x) for x in obj]
    return obj


# ----------------------------------------------------------------------
# Images
# ----------------------------------------------------------------------
EXT_OK = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".tif", ".tiff",
          ".heic", ".avif"}
MIME   = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
          ".webp": "image/webp", ".svg": "image/svg+xml", ".bmp": "image/bmp",
          ".tif": "image/tiff", ".tiff": "image/tiff", ".avif": "image/avif"}


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
    mime = MIME.get(img.get("ext", ".png"), "image/png")
    return f"data:{mime};base64," + base64.b64encode(img["bytes"]).decode()


def _load_custom_icon_data_uri(path: str) -> str:
    """Load a custom icon file and return as a data URI."""
    try:
        p = Path(path)
        if not p.exists():
            return ""
        raw = p.read_bytes()
        ext  = p.suffix.lower()
        mime = MIME.get(ext, "image/png")
        return f"data:{mime};base64," + base64.b64encode(raw).decode()
    except Exception:
        return ""


INTERNAL_RE = re.compile(r"^(/|https?://(www\.)?notion\.(so|site))", re.I)


class R:
    """Rendering context shared by the HTML / Markdown / Text / Word writers."""

    def __init__(self, cfg, kind, base_dir=None):
        self.cfg, self.kind, self.base_dir = cfg, kind, base_dir
        self.expand = bool(cfg.get("expand_toggles", True))
        self.links  = cfg.get("links", LINK_MODES[0])

    def keep_link(self, href):
        if not href:
            return False
        if self.links == LINK_MODES[1]:
            return False
        if self.links == LINK_MODES[2]:
            return not INTERNAL_RE.match(href)
        return True

    def img_src(self, img):
        path, data, url = img.get("path"), img.get("bytes"), img["url"]
        handling = self.cfg.get("img_handling", IMG_MODES[0])
        if self.kind == "pdf":
            if img.get("opt_bytes"):
                return f"data:{img.get('opt_mime', 'image/jpeg')};base64," + \
                    base64.b64encode(img["opt_bytes"]).decode()
            if path:
                return Path(path).resolve().as_uri()
            return data_uri(img) if data else url
        if handling == IMG_MODES[2]:
            return url
        if handling == IMG_MODES[0] and data and self.kind == "html":
            return data_uri(img)
        if path and self.base_dir:
            rel = os.path.relpath(path, self.base_dir).replace(os.sep, "/")
            return quote(rel, safe="/")
        if data and self.kind == "html":
            return data_uri(img)
        return url


# ----------------------------------------------------------------------
# CSS / HTML building helpers
# ----------------------------------------------------------------------
esc = _html.escape

TEXT_COLORS = {"gray": "#787774", "brown": "#9f6b53", "orange": "#d9730d", "yellow": "#cb912f",
               "green": "#448361", "blue": "#337ea9", "purple": "#9065b0", "pink": "#c14c8a",
               "red": "#d44c47"}
BG_COLORS   = {"gray": "#f1f1ef", "brown": "#f4eeee", "orange": "#fbecdd", "yellow": "#fbf3db",
               "green": "#edf3ec", "blue": "#e7f3f8", "purple": "#f6f3f9", "pink": "#faf1f5",
               "red": "#fdebec"}

_FONT_STACKS = {
    "Sans-serif": "ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif",
    "Serif":      "Georgia, Cambria, 'Times New Roman', Times, serif",
    "Monospace":  "'Cascadia Code', Consolas, 'Courier New', Courier, monospace",
}
_FALLBACK_TAIL = {
    "sans":   "'Segoe UI', Helvetica, Arial, sans-serif",
    "serif":  "Georgia, 'Times New Roman', serif",
    "mono":   "Consolas, 'Courier New', monospace",
    "arabic": "'Segoe UI', Tahoma, Arial, sans-serif",
}


def _safe_font_name(name):
    return re.sub(r"[^\w \-]", "", name or "").strip()


def _font_stack(name):
    if name in _FONT_STACKS:
        return _FONT_STACKS[name]
    n = _safe_font_name(name)
    if not n:
        return _FONT_STACKS["Sans-serif"]
    return f"'{n}', " + _FALLBACK_TAIL[FONT_CATEGORY.get(name, "sans")]


def _web_font_links(cfg):
    """<link> tags for Google Fonts (only when enabled; needs internet at export/view time)."""
    if not cfg.get("web_fonts"):
        return ""
    names = []
    for key in ("font_family", "heading_font"):
        n = cfg.get(key, "")
        if n in GOOGLE_FONTS and n not in names:
            names.append(n)
    if not names:
        return ""
    fam = "&".join("family=" + quote(n).replace("%20", "+") + ":wght@400;700" for n in names)
    return ('<link rel="preconnect" href="https://fonts.googleapis.com">'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?{fam}&display=swap">')


KATEX_HEAD = (
    '<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.css">'
    '<script defer src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.js"></script>'
    "<script>window.addEventListener('load',function(){if(!window.katex)return;"
    "document.querySelectorAll('.eq').forEach(function(el){try{katex.render(el.textContent,el,"
    "{throwOnError:false,displayMode:el.tagName==='DIV'});}catch(e){}});});</script>"
)

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

_CSS_TEMPLATE = r"""
/* ---- PageOut for Notion: Notion-like stylesheet ---- */
*, *::before, *::after { box-sizing: border-box; }
:root { --accent: @@ACCENT@@; --ink: #37352f; --muted: rgba(55,53,47,.65); --line: rgba(55,53,47,.09);
        --line2: #e9e9e7; --soft: #f7f6f3; --callout: rgba(241,241,239,.6); }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body {
  font-family: @@BODY_FONT@@, 'Segoe UI Emoji', 'Apple Color Emoji', 'Noto Color Emoji';
  max-width: 900px; margin: 2rem auto; padding: 0 1.6rem;
  color: var(--ink); line-height: @@LINE@@; font-size: @@SIZE@@px; text-align: @@ALIGN@@;
  -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility; font-kerning: normal;
  overflow-wrap: break-word;
}
/* Arabic / Hebrew paragraphs flow right-to-left automatically */
p, li, h1, h2, h3, blockquote, summary, td, th, figcaption, .callout-body { unicode-bidi: plaintext; }
p { margin: .28em 0; orphans: 3; widows: 3; }

/* title + icon */
.notion-page-icon { font-size: 78px; line-height: 1.1; display: block; text-align: @@HALIGN@@;
  margin: 0 0 .12em; user-select: none; }
.notion-page-icon img { height: 78px; width: auto; display: inline-block; vertical-align: bottom; }
h1.notion-title { font-family: @@HEAD_FONT@@; font-size: @@H1REM@@rem; font-weight: 700; line-height: 1.2;
  margin: 0 0 .25em; text-align: @@HALIGN@@; color: var(--ink); break-after: avoid; @@SEP@@ }

/* headings */
h1, h2, h3 { font-family: @@HEAD_FONT@@; font-weight: 600; line-height: 1.3; text-align: @@HALIGN@@;
  color: var(--accent); break-after: avoid; }
h1 { font-size: 1.875em; margin: 1.6em 0 .2em; }
h2 { font-size: 1.5em;   margin: 1.3em 0 .2em; }
h3 { font-size: 1.25em;  margin: 1.1em 0 .15em; }

a { color: var(--accent); text-decoration: underline; text-decoration-color: rgba(55,53,47,.4);
    text-decoration-thickness: .05em; text-underline-offset: 2px; }
strong { font-weight: 600; }

/* cover page */
.notion-cover-page { display: flex; flex-direction: column; justify-content: center; min-height: 60vh; padding: 3rem 0 2rem; }
.notion-page-break { page-break-after: always; break-after: page; height: 0; margin: 0; }
@media print { .notion-cover-page { min-height: 80vh; } }

/* properties (Notion style: plain key / value rows) */
table.props-table { border-collapse: collapse; margin: .7em 0 1.4em; width: 100%; font-size: .95em;
  border: none; border-bottom: 1px solid var(--line); }
table.props-table th { width: 24%; color: var(--muted); font-weight: 400; background: none; text-align: left;
  padding: .28em .8em .28em 0; border: none; vertical-align: top; }
table.props-table td { padding: .28em .3em; border: none; vertical-align: top; }
.props-pills { display: flex; flex-wrap: wrap; gap: .35em; margin: .7em 0 1.3em; }
.props-pills .pill { display: inline-flex; align-items: center; gap: .35em; background: var(--soft);
  border-radius: 4px; padding: .12em .6em; font-size: .85em; line-height: 1.5; }
.props-pills .pill-key { color: var(--muted); }
dl.props-list { margin: .6em 0 1.5em; display: grid; grid-template-columns: auto 1fr; gap: .2em 1.2em; font-size: .95em; }
dl.props-list dt { color: var(--muted); white-space: nowrap; }
dl.props-list dd { margin: 0; }

/* tables (Notion simple table) */
table { border-collapse: collapse; margin: 1em 0; width: 100%; font-size: .95em; }
thead { display: table-header-group; } tr { break-inside: avoid; }
td, th { border: 1px solid var(--line2); padding: .4em .65em; vertical-align: top; text-align: left; }
table:not(.props-table) th { background: var(--soft); font-weight: 500; }

/* quotes, code, callouts */
blockquote { border-left: 3px solid currentColor; margin: .6em 0; padding: 0 .9em; font-size: 1.2em; line-height: 1.5; }
pre { background: var(--soft); border-radius: 4px; padding: 1.5em 1.1em 1.5em 1.7em; overflow: auto;
  white-space: pre-wrap; word-break: break-word; font-size: .85em; line-height: 1.5; margin: .8em 0; tab-size: 2; }
code { background: rgba(135,131,120,.15); color: #eb5757; padding: .2em .4em; border-radius: 3px;
  font-family: @@CODE_FONT@@; font-size: 85%; }
pre, pre code { font-family: @@CODE_FONT@@; }
pre code { background: none; color: inherit; padding: 0; font-size: 1em; border-radius: 0; }
.callout { display: flex; gap: .7em; border-radius: 4px; padding: 1em 1em 1em .8em; margin: .8em 0;
  background: var(--callout); border: 1px solid var(--line2); }
.callout .callout-icon { font-size: 1.3em; line-height: 1.4; flex-shrink: 0; }
.callout .callout-body { flex: 1; min-width: 0; }
.callout .callout-body > :first-child { margin-top: 0; } .callout .callout-body > :last-child { margin-bottom: 0; }
details { margin: .3em 0; } summary { cursor: pointer; font-weight: 400; }
details > *:not(summary) { margin-left: 1.4em; }
.eq { font-family: 'Cambria Math', 'STIX Two Math', 'Times New Roman', serif; }
div.eq { text-align: center; margin: .9em 0; overflow-x: auto; }

/* images */
figure { margin: .8em 0; }
figure img { max-width: 100%; height: auto; border-radius: 3px; display: block; margin: 0 auto; }
figcaption { color: var(--muted); font-size: .85em; margin-top: .4em; text-align: center; }
.maximize-images figure img { width: 100%; object-fit: contain; }
.one-image-per-page figure { page-break-after: always; break-after: page; }

/* lists */
ul, ol { padding-left: 1.5em; margin: .2em 0; } li { margin: .1em 0; }
ul { list-style: disc; } ul ul { list-style: circle; } ul ul ul { list-style: square; }
ol { list-style: decimal; } ol ol { list-style: lower-alpha; } ol ol ol { list-style: lower-roman; }
ul.todo { list-style: none; padding-left: .2em; } ul.todo input { accent-color: var(--accent); margin-right: .4em; }
hr { border: none; border-top: 1px solid var(--line); margin: 1.2em 0; }
.indent { margin-left: 1.5em; }
.cols { display: flex; gap: 1.6em; } .col { flex: 1; min-width: 0; }
section.page { margin-bottom: 3em; } .subpage { margin-top: 2em; }

@media print {
  body { max-width: none; margin: 0; padding: 0; }
  pre, figure, .callout, blockquote { break-inside: avoid; }
}
"""


def _build_html_css(cfg: dict) -> str:
    """Full stylesheet built from the user's design settings."""
    body_font = _font_stack(cfg.get("font_family", "Sans-serif"))
    hf        = cfg.get("heading_font", SAME_AS_BODY)
    head_font = body_font if hf in ("", SAME_AS_BODY) else _font_stack(hf)
    accent    = cfg.get("accent_color", "#37352f")
    if not _HEX_RE.match(str(accent)):
        accent = "#37352f"
    size  = int(cfg.get("base_font_size", 16))
    align = "justify" if str(cfg.get("text_align", "Left")).lower() == "justify" else "start"
    halign = "center" if str(cfg.get("heading_align", "Left")).lower() == "center" else "start"
    sep = "border-bottom: 3px solid var(--accent); padding-bottom: .3em;" if cfg.get("title_separator") else ""
    repl = {
        "@@ACCENT@@": accent, "@@BODY_FONT@@": body_font, "@@HEAD_FONT@@": head_font,
        "@@CODE_FONT@@": _FONT_STACKS["Monospace"], "@@LINE@@": str(float(cfg.get("line_spacing", 1.6))),
        "@@SIZE@@": str(size), "@@ALIGN@@": align, "@@HALIGN@@": halign,
        "@@H1REM@@": str(round(2.5 * size / 16, 2)), "@@SEP@@": sep,
    }
    css = _CSS_TEMPLATE
    for k, v in repl.items():
        css = css.replace(k, v)
    return css


def color_style(color):
    if not color or color == "default":
        return ""
    if color.endswith("_background"):
        c = BG_COLORS.get(color[:-11])
        return f"background:{c};" if c else ""
    c = TEXT_COLORS.get(color)
    return f"color:{c};" if c else ""


# ----------------------------------------------------------------------
# Property HTML rendering  (all four layouts)
# ----------------------------------------------------------------------
def props_html(rows, layout: str, cfg: dict) -> str:
    """Render property rows according to the chosen layout style."""
    if not rows or layout == "Hidden":
        return ""
    if layout == "Notion Table":
        inner = "".join(
            f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in rows
        )
        return f'<table class="props-table">{inner}</table>'
    if layout == "Inline Pills":
        pills = "".join(
            f'<span class="pill"><span class="pill-key">{esc(k)}:</span>'
            f'<span class="pill-val">{esc(v)}</span></span>'
            for k, v in rows
        )
        return f'<div class="props-pills">{pills}</div>'
    if layout == "Minimalist List":
        items = "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in rows)
        return f'<dl class="props-list">{items}</dl>'
    return ""


# ----------------------------------------------------------------------
# Icon HTML
# ----------------------------------------------------------------------
def _page_icon_html(page, cfg: dict) -> str:
    """Return an HTML snippet for the page icon based on icon_mode setting."""
    mode = cfg.get("icon_mode", ICON_MODES[0])
    if mode == "Hide icon":
        return ""
    if mode == "Custom icon file":
        path = cfg.get("icon_custom_file", "")
        if path:
            uri = _load_custom_icon_data_uri(path)
            if uri:
                return f'<span class="notion-page-icon"><img src="{esc(uri, quote=True)}" alt="icon"></span>'
        # fall through to page icon
    # Show page icon (default)
    if page:
        icon = page.get("icon") or {}
        if icon.get("type") == "emoji":
            return f'<span class="notion-page-icon">{esc(icon["emoji"])}</span>'
        if icon.get("type") in ("external", "file"):
            url = (icon.get(icon.get("type")) or {}).get("url", "")
            if url:
                return (f'<span class="notion-page-icon">'
                        f'<img src="{esc(url, quote=True)}" alt="icon"></span>')
    return ""


# ----------------------------------------------------------------------
# Caption formatting helper
# ----------------------------------------------------------------------
def _build_caption(fmt_template: str, img: dict, img_num: int) -> str:
    """Build an image caption from the template."""
    url  = img.get("url", "")
    path = img.get("path", "") or url
    base = os.path.basename(unquote(urlparse(url).path))
    name, _ext = os.path.splitext(base)
    ext  = (_ext.lstrip(".")) if _ext else img.get("ext", ".png").lstrip(".")
    caption_text = img.get("caption", "")
    original     = name
    result = fmt_template
    result = result.replace("{name}",     name or base)
    result = result.replace("{ext}",      ext)
    result = result.replace("{n}",        str(img_num))
    result = result.replace("{original}", original)
    result = result.replace("{caption}",  caption_text)
    return result


# ----------------------------------------------------------------------
# HTML renderer
# ----------------------------------------------------------------------
def rt_html(rts, r):
    out = []
    for x in rts or []:
        a = x.get("annotations", {})
        if x.get("type") == "equation":
            s = f'<span class="eq">{esc(x["equation"]["expression"])}</span>'
        else:
            s = esc(x.get("plain_text", "")).replace("\n", "<br>")
        if a.get("code"):
            s = f"<code>{s}</code>"
        if a.get("bold"):
            s = f"<strong>{s}</strong>"
        if a.get("italic"):
            s = f"<em>{s}</em>"
        if a.get("strikethrough"):
            s = f"<s>{s}</s>"
        if a.get("underline"):
            s = f"<u>{s}</u>"
        st = color_style(a.get("color"))
        if st:
            s = f'<span style="{st}">{s}</span>'
        href = x.get("href")
        if href and r.keep_link(href):
            s = f'<a href="{esc(href, quote=True)}">{s}</a>'
        out.append(s)
    return "".join(out)


def blocks_html(blocks, r, img_counter=None):
    if img_counter is None:
        img_counter = [0]
    out, i = [], 0
    while i < len(blocks):
        b = blocks[i]
        t = b["type"]
        if t in LIST_TYPES:
            tag  = "ol" if t == "numbered_list_item" else "ul"
            cls  = ' class="todo"' if t == "to_do" else ""
            items = []
            while i < len(blocks) and blocks[i]["type"] == t:
                bb    = blocks[i]
                d     = bb[t]
                inner = rt_html(d.get("rich_text"), r)
                if t == "to_do":
                    chk   = " checked" if d.get("checked") else ""
                    inner = f'<input type="checkbox" disabled{chk}> ' + inner
                items.append(f"<li>{inner}{blocks_html(bb.get('children', []), r, img_counter)}</li>")
                i += 1
            out.append(f"<{tag}{cls}>{''.join(items)}</{tag}>")
            continue
        out.append(block_html(b, r, img_counter))
        i += 1
    return "\n".join(x for x in out if x)


def block_html(b, r, img_counter=None):
    if img_counter is None:
        img_counter = [0]
    t    = b["type"]
    d    = b.get(t) or {}
    kids = b.get("children", [])
    cfg  = r.cfg

    def rt():
        return rt_html(d.get("rich_text"), r)

    def sub():
        return blocks_html(kids, r, img_counter)

    def indent():
        return f'<div class="indent">{sub()}</div>' if kids else ""

    if t == "paragraph":
        return f"<p>{rt() or '<br>'}</p>" + indent()
    if t in ("heading_1", "heading_2", "heading_3"):
        n = t[-1]
        return f"<h{n}>{rt()}</h{n}>" + indent()
    if t == "toggle":
        op = " open" if r.expand else ""
        return f"<details{op}><summary>{rt()}</summary>{sub()}</details>"
    if t == "quote":
        return f"<blockquote>{rt()}{sub()}</blockquote>"
    if t == "callout":
        ic    = d.get("icon") or {}
        emoji = ic.get("emoji", "") if ic.get("type") == "emoji" else "💡"
        st    = color_style(d.get("color"))
        st_   = f' style="{st}"' if st else ""
        return (f'<div class="callout"{st_}>'
                f'<span class="callout-icon">{esc(emoji)}</span>'
                f'<div class="callout-body">{rt()}{sub()}</div></div>')
    if t == "code":
        lang = esc(d.get("language", ""))
        cap  = rt_html(d.get("caption"), r)
        return (f'<pre><code class="language-{lang}">{esc(plain(d.get("rich_text")))}</code></pre>'
                + (f"<p><em>{cap}</em></p>" if cap else ""))
    if t == "divider":
        return "<hr>"
    if t == "equation":
        return f'<div class="eq">{esc(d.get("expression", ""))}</div>'
    if t == "image":
        img = b.get("_img")
        if not img:
            url = (d.get(d.get("type")) or {}).get("url", "")
            if not url:
                return ""
            img = {"url": url}
        img_counter[0] += 1
        num = img_counter[0]
        # Determine caption
        notion_cap = rt_html(d.get("caption"), r)
        show_names = cfg.get("show_image_names", False)
        caption_html = ""
        if show_names and not notion_cap:
            cap_text = _build_caption(cfg.get("caption_format", "{name}"), img, num)
            caption_html = f"<figcaption>{esc(cap_text)}</figcaption>"
        elif notion_cap:
            caption_html = f"<figcaption>{notion_cap}</figcaption>"
        # Page-break after image?
        one_per = cfg.get("one_image_per_page", False)
        style   = ' style="page-break-after:always;break-after:page;"' if one_per else ""
        return (f'<figure{style}><img src="{esc(r.img_src(img), quote=True)}" '
                f'alt="{esc(plain(d.get("caption")))}">'
                + caption_html + "</figure>")
    if t in ("video", "file", "pdf", "audio"):
        src  = d.get(d.get("type")) or {}
        url  = src.get("url", "")
        name = plain(d.get("caption")) or d.get("name") or url.split("?")[0].rsplit("/", 1)[-1] or t
        if d.get("type") == "external" and r.keep_link(url):
            return f'<p>📎 <a href="{esc(url, quote=True)}">{esc(name)}</a></p>'
        return f"<p>📎 {esc(name)}</p>"
    if t in ("bookmark", "embed", "link_preview"):
        url  = d.get("url", "")
        text = plain(d.get("caption")) or url
        if r.keep_link(url):
            return f'<p>🔗 <a href="{esc(url, quote=True)}">{esc(text)}</a></p>'
        return f"<p>🔗 {esc(text)}</p>"
    if t == "table":
        rows  = [x for x in kids if x["type"] == "table_row"]
        hdr, rhdr = d.get("has_column_header"), d.get("has_row_header")
        s = ["<table>"]
        for ri, row in enumerate(rows):
            cells = []
            for ci, c in enumerate(row["table_row"]["cells"]):
                tag = "th" if (hdr and ri == 0) or (rhdr and ci == 0) else "td"
                cells.append(f"<{tag}>{rt_html(c, r)}</{tag}>")
            s.append("<tr>" + "".join(cells) + "</tr>")
        s.append("</table>")
        return "".join(s)
    if t == "column_list":
        cols = "".join(f'<div class="col">{blocks_html(c.get("children", []), r, img_counter)}</div>' for c in kids)
        return f'<div class="cols">{cols}</div>'
    if t in ("column", "synced_block"):
        return sub()
    if t == "child_page":
        s = b.get("_sub")
        if s:
            return (f'<section class="subpage"><h2>📄 {esc(s["title"])}</h2>'
                    f'{blocks_html(s["tree"], r, img_counter)}</section>')
        return f'<p class="subpage">📄 {esc(d.get("title", ""))}</p>'
    if t == "child_database":
        return f'<p class="subpage">🗂 {esc(d.get("title", ""))} (database)</p>'
    if t == "link_to_page":
        return "<p>↪ linked page</p>"
    if t in ("table_of_contents", "breadcrumb", "table_row"):
        return ""
    if "rich_text" in d:
        return f"<p>{rt()}</p>" + indent()
    return ""


def wrap_html(title, body, cfg):
    css  = _build_html_css(cfg) + (cfg.get("custom_css") or "")
    body_classes = []
    if cfg.get("maximize_images"):
        body_classes.append("maximize-images")
    if cfg.get("one_image_per_page"):
        body_classes.append("one-image-per-page")
    cls_attr = f' class="{" ".join(body_classes)}"' if body_classes else ""
    head_extra = _web_font_links(cfg)
    if cfg.get("render_math", True) and 'class="eq"' in body:
        head_extra += KATEX_HEAD
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{esc(title)}</title>{head_extra}<style>{css}</style></head>'
            f'<body{cls_attr}>{body}</body></html>')


# ----------------------------------------------------------------------
# Markdown / Text renderers  (unchanged logic, kept for completeness)
# ----------------------------------------------------------------------
def _wrap_ws(s, left, right):
    core = s.strip()
    if not core:
        return s
    lead = s[:len(s) - len(s.lstrip())]
    tail = s[len(s.rstrip()):]
    return f"{lead}{left}{core}{right}{tail}"


def rt_md(rts, r):
    out = []
    for x in rts or []:
        a = x.get("annotations", {})
        s = f"${x['equation']['expression']}$" if x.get("type") == "equation" else x.get("plain_text", "")
        if a.get("code"):
            s = _wrap_ws(s, "`", "`")
        if a.get("bold"):
            s = _wrap_ws(s, "**", "**")
        if a.get("italic"):
            s = _wrap_ws(s, "*", "*")
        if a.get("strikethrough"):
            s = _wrap_ws(s, "~~", "~~")
        if a.get("underline"):
            s = _wrap_ws(s, "<u>", "</u>")
        href = x.get("href")
        if href and r.keep_link(href):
            s = _wrap_ws(s, "[", f"]({href})")
        out.append(s)
    return "".join(out)


def _trim(lines):
    while lines and lines[-1] == "":
        lines = lines[:-1]
    return lines


def blocks_md(blocks, r, depth=0):
    lines, num, prev = [], 0, None
    pad = "    " * depth
    for b in blocks:
        t    = b["type"]
        d    = b.get(t) or {}
        kids = b.get("children", [])
        num  = num + 1 if t == "numbered_list_item" else 0
        text = rt_md(d.get("rich_text"), r) if isinstance(d, dict) else ""
        if t in LIST_TYPES:
            if prev in LIST_TYPES and prev != t and lines and lines[-1] != "":
                lines.append("")
            prev = t
            if t == "bulleted_list_item":
                marker = "- "
            elif t == "numbered_list_item":
                marker = f"{num}. "
            else:
                marker = "- [x] " if d.get("checked") else "- [ ] "
            lines.append(pad + marker + text)
            lines.extend(_trim(blocks_md(kids, r, depth + 1)))
            continue
        prev = t
        if lines and lines[-1] != "":
            lines.append("")
        block = []
        after = kids
        if t == "paragraph":
            block = [pad + text]
        elif t in ("heading_1", "heading_2", "heading_3"):
            block = [pad + "#" * int(t[-1]) + " " + text]
        elif t in ("quote", "callout"):
            icon = ""
            if t == "callout" and (d.get("icon") or {}).get("type") == "emoji":
                icon = d["icon"]["emoji"] + " "
            inner = (icon + text + "\n" + "\n".join(_trim(blocks_md(kids, r)))).strip("\n")
            block = [pad + ("> " + ln if ln else ">") for ln in inner.split("\n")]
            after = []
        elif t == "code":
            block = ([pad + "```" + d.get("language", "")] +
                     [pad + ln for ln in plain(d.get("rich_text")).split("\n")] +
                     [pad + "```"])
        elif t == "divider":
            block = [pad + "---"]
        elif t == "equation":
            block = [pad + "$$ " + d.get("expression", "") + " $$"]
        elif t == "image":
            img = b.get("_img")
            if not img:
                url = (d.get(d.get("type")) or {}).get("url", "")
                img = {"url": url} if url else None
            if img:
                block = [pad + f"![{plain(d.get('caption'))}]({r.img_src(img)})"]
        elif t in ("video", "file", "pdf", "audio"):
            src  = d.get(d.get("type")) or {}
            url  = src.get("url", "")
            name = plain(d.get("caption")) or d.get("name") or url.split("?")[0].rsplit("/", 1)[-1] or t
            block = [pad + (f"[{name}]({url})" if d.get("type") == "external" and r.keep_link(url) else name)]
        elif t in ("bookmark", "embed", "link_preview"):
            url  = d.get("url", "")
            block = [pad + (f"[{plain(d.get('caption')) or url}]({url})" if r.keep_link(url) else url)]
        elif t == "toggle":
            block = ([pad + f"<details><summary>{text}</summary>", ""] +
                     _trim(blocks_md(kids, r, depth)) + ["", pad + "</details>"])
            after = []
        elif t == "table":
            rows = [[rt_md(c, r).replace("|", "\\|").replace("\n", " ") for c in row["table_row"]["cells"]]
                    for row in kids if row["type"] == "table_row"]
            if rows:
                width = max(len(x) for x in rows)
                rows  = [x + [""] * (width - len(x)) for x in rows]
                block = ([pad + "| " + " | ".join(rows[0]) + " |",
                          pad + "| " + " | ".join(["---"] * width) + " |"] +
                         [pad + "| " + " | ".join(x) + " |" for x in rows[1:]])
            after = []
        elif t == "column_list":
            for c in kids:
                block += _trim(blocks_md(c.get("children", []), r, depth)) + [""]
            block = _trim(block)
            after = []
        elif t in ("column", "synced_block"):
            block = _trim(blocks_md(kids, r, depth))
            after = []
        elif t == "child_page":
            s = b.get("_sub")
            if s:
                block = ([pad + "## 📄 " + s["title"], ""] +
                         _trim(blocks_md(s["tree"], r, depth)))
            else:
                block = [pad + "📄 " + d.get("title", "")]
            after = []
        elif t == "child_database":
            block = [pad + "🗂 " + d.get("title", "") + " (database)"]
        elif t == "link_to_page":
            block = [pad + "↪ linked page"]
        elif isinstance(d, dict) and "rich_text" in d:
            block = [pad + text]
        if not block:
            continue
        lines.extend(block)
        lines.append("")
        if after:
            lines.extend(_trim(blocks_md(after, r, depth + 1)))
            lines.append("")
    return _trim(lines)


def md_front_matter(title, rows):
    out = ["---", "title: " + json.dumps(title, ensure_ascii=False)]
    for k, v in rows:
        out.append(f"{json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}")
    out.append("---")
    return "\n".join(out)


def blocks_txt(blocks, depth=0):
    lines, num = [], 0
    pad = "  " * depth
    for b in blocks:
        t    = b["type"]
        d    = b.get(t) or {}
        kids = b.get("children", [])
        num  = num + 1 if t == "numbered_list_item" else 0
        text = plain(d.get("rich_text")) if isinstance(d, dict) else ""
        if t == "bulleted_list_item":
            lines.append(f"{pad}• {text}")
        elif t == "numbered_list_item":
            lines.append(f"{pad}{num}. {text}")
        elif t == "to_do":
            lines.append(f"{pad}[{'x' if d.get('checked') else ' '}] {text}")
        elif t in ("heading_1", "heading_2", "heading_3"):
            lines += ["", pad + text.upper() if t == "heading_1" else pad + text, ""]
        elif t == "divider":
            lines.append(pad + "-" * 30)
        elif t == "image":
            lines.append(f"{pad}[Image{': ' + plain(d.get('caption')) if d.get('caption') else ''}]")
        elif t == "table":
            for row in kids:
                if row["type"] == "table_row":
                    lines.append(pad + "\t".join(plain(c) for c in row["table_row"]["cells"]))
            kids = []
        elif t == "child_page":
            s = b.get("_sub")
            lines += ["", f"{pad}== {(s or {}).get('title') or d.get('title', '')} =="]
            if s:
                lines += blocks_txt(s["tree"], depth)
        elif t == "equation":
            lines.append(pad + d.get("expression", ""))
        elif t in ("bookmark", "embed", "link_preview"):
            lines.append(pad + d.get("url", ""))
        elif t == "code":
            lines += [pad + ln for ln in plain(d.get("rich_text")).split("\n")]
        elif t in ("column_list", "column", "synced_block"):
            lines += blocks_txt(kids, depth)
            kids = []
        elif isinstance(d, dict) and "rich_text" in d:
            lines.append(pad + text)
        if kids:
            lines += blocks_txt(kids, depth + 1)
    return lines


# ----------------------------------------------------------------------
# Word renderer
# ----------------------------------------------------------------------
def build_docx(title, icon_text, rows, tree, r, path, cfg):
    try:
        from docx import Document
        from docx.shared import Inches, Pt, RGBColor
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        raise Exception("Word export needs: pip install python-docx")

    doc = Document()

    # Page icon (emoji only for Word)
    icon_mode = cfg.get("icon_mode", ICON_MODES[0])
    if icon_mode != "Hide icon" and icon_text:
        p = doc.add_paragraph()
        p.add_run(icon_text).font.size = Pt(28)

    # Title
    heading = doc.add_heading(title, 0)
    if cfg.get("heading_align") == "Center":
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Title separator
    if cfg.get("title_separator"):
        p = doc.add_paragraph()
        p.add_run("─" * 40).font.color.rgb = RGBColor(0xE3, 0xE2, 0xE0)

    # Properties
    prop_layout = cfg.get("prop_layout", "Notion Table")
    if rows and prop_layout != "Hidden":
        if prop_layout in ("Notion Table", "Minimalist List"):
            tb = doc.add_table(rows=0, cols=2)
            tb.style = "Table Grid"
            for k, v in rows:
                cells = tb.add_row().cells
                cells[0].text = k
                cells[1].text = v
                cells[0].paragraphs[0].runs[0].font.color.rgb = RGBColor(0x78, 0x77, 0x74)
        elif prop_layout == "Inline Pills":
            p = doc.add_paragraph()
            for i, (k, v) in enumerate(rows):
                if i:
                    p.add_run("  ")
                run = p.add_run(f"{k}: {v}")
                run.font.size = Pt(9)
        doc.add_paragraph()

    # Cover page break
    if cfg.get("cover_page"):
        from docx.oxml.ns import qn as _qn
        from docx.oxml import OxmlElement as _OE
        p = doc.add_paragraph()
        pPr = p._p.get_or_add_pPr()
        pb  = _OE("w:pageBreakBefore")
        pb.set(_qn("w:val"), "true")
        pPr.append(pb)

    def hyperlink(par, text, url):
        rid = par.part.relate_to(
            url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
            is_external=True)
        h    = OxmlElement("w:hyperlink")
        h.set(qn("r:id"), rid)
        run  = OxmlElement("w:r")
        rpr  = OxmlElement("w:rPr")
        u    = OxmlElement("w:u")
        u.set(qn("w:val"), "single")
        col  = OxmlElement("w:color")
        col.set(qn("w:val"), "0563C1")
        rpr.append(u)
        rpr.append(col)
        run.append(rpr)
        tx   = OxmlElement("w:t")
        tx.text = text
        run.append(tx)
        h.append(run)
        par._p.append(h)

    def runs(par, rts):
        for x in rts or []:
            txt = x.get("plain_text", "")
            if not txt:
                continue
            href = x.get("href")
            if href and r.keep_link(href):
                hyperlink(par, txt, href)
                continue
            run = par.add_run(txt)
            a   = x.get("annotations", {})
            run.bold      = True if a.get("bold") else None
            run.italic    = True if a.get("italic") else None
            run.underline = True if a.get("underline") else None
            run.font.strike = True if a.get("strikethrough") else None
            if a.get("code"):
                run.font.name = "Consolas"

    def do_indent(par, depth):
        if depth:
            par.paragraph_format.left_indent = Inches(0.3 * depth)

    img_num = [0]

    def add(blocks, depth=0):
        for b in blocks:
            t    = b["type"]
            d    = b.get(t) or {}
            kids = b.get("children", [])
            lvl  = min(depth + 1, 3)
            if t == "paragraph":
                p = doc.add_paragraph()
                runs(p, d.get("rich_text"))
                do_indent(p, depth)
            elif t in ("heading_1", "heading_2", "heading_3"):
                p = doc.add_heading(level=int(t[-1]))
                runs(p, d.get("rich_text"))
                if cfg.get("heading_align") == "Center":
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            elif t == "bulleted_list_item":
                p = doc.add_paragraph(style="List Bullet" if lvl == 1 else f"List Bullet {lvl}")
                runs(p, d.get("rich_text"))
            elif t == "numbered_list_item":
                p = doc.add_paragraph(style="List Number" if lvl == 1 else f"List Number {lvl}")
                runs(p, d.get("rich_text"))
            elif t == "to_do":
                p = doc.add_paragraph("☑ " if d.get("checked") else "☐ ")
                runs(p, d.get("rich_text"))
                do_indent(p, depth)
            elif t in ("quote", "callout"):
                p = doc.add_paragraph(style="Quote")
                if t == "callout" and (d.get("icon") or {}).get("type") == "emoji":
                    p.add_run(d["icon"]["emoji"] + " ")
                runs(p, d.get("rich_text"))
            elif t == "toggle":
                p = doc.add_paragraph()
                runs(p, d.get("rich_text"))
                for run in p.runs:
                    run.bold = True
                do_indent(p, depth)
            elif t == "code":
                p     = doc.add_paragraph()
                run   = p.add_run(plain(d.get("rich_text")))
                run.font.name = "Consolas"
                do_indent(p, depth)
            elif t == "divider":
                doc.add_paragraph("─" * 20)
            elif t == "equation":
                doc.add_paragraph(d.get("expression", ""))
            elif t == "image":
                img = b.get("_img")
                img_num[0] += 1
                if img and img.get("bytes"):
                    try:
                        doc.add_picture(io.BytesIO(img.get("opt_bytes") or img["bytes"]), width=Inches(5.5))
                        # Caption
                        show_names = cfg.get("show_image_names", False)
                        cap_text   = plain(d.get("caption"))
                        if not cap_text and show_names:
                            cap_text = _build_caption(cfg.get("caption_format", "{name}"),
                                                      img, img_num[0])
                        if cap_text:
                            doc.add_paragraph(cap_text)
                        # One per page
                        if cfg.get("one_image_per_page"):
                            from docx.oxml.ns import qn as _qn
                            from docx.oxml import OxmlElement as _OE
                            p2  = doc.add_paragraph()
                            pPr = p2._p.get_or_add_pPr()
                            pb  = _OE("w:pageBreakBefore")
                            pb.set(_qn("w:val"), "true")
                            pPr.append(pb)
                    except Exception:
                        doc.add_paragraph(f"[Image: {img['url']}]")
                elif img:
                    doc.add_paragraph(f"[Image: {img['url']}]")
            elif t in ("bookmark", "embed", "link_preview"):
                p   = doc.add_paragraph()
                url = d.get("url", "")
                if r.keep_link(url):
                    hyperlink(p, url, url)
                else:
                    p.add_run(url)
            elif t in ("video", "file", "pdf", "audio"):
                src = d.get(d.get("type")) or {}
                doc.add_paragraph("📎 " + (plain(d.get("caption")) or d.get("name") or src.get("url", "")))
            elif t == "table":
                rws = [x["table_row"]["cells"] for x in kids if x["type"] == "table_row"]
                if rws:
                    width = max(len(x) for x in rws)
                    tb    = doc.add_table(rows=len(rws), cols=width)
                    tb.style = "Table Grid"
                    for ri, row in enumerate(rws):
                        for ci, c in enumerate(row):
                            tb.cell(ri, ci).text = plain(c)
                kids = []
            elif t == "column_list":
                for c in kids:
                    add(c.get("children", []), depth)
                kids = []
            elif t in ("column", "synced_block"):
                add(kids, depth)
                kids = []
            elif t == "child_page":
                s = b.get("_sub")
                if s:
                    doc.add_heading("📄 " + s["title"], level=2)
                    add(s["tree"], depth)
                else:
                    doc.add_paragraph("📄 " + d.get("title", ""))
            elif t == "child_database":
                doc.add_paragraph("🗂 " + d.get("title", "") + " (database)")
            elif "rich_text" in d:
                p = doc.add_paragraph()
                runs(p, d.get("rich_text"))
            if kids and t not in ("table",):
                add(kids, depth + 1)

    add(tree)
    try:   # drop a trailing empty "page break" paragraph (would create a blank last page)
        last = doc.paragraphs[-1]
        if not last.text.strip() and last._p.xpath(".//w:pageBreakBefore"):
            last._p.getparent().remove(last._p)
    except Exception:
        pass
    doc.save(path)


# ----------------------------------------------------------------------
# LaTeX renderer & Gemini Vision Math OCR
# ----------------------------------------------------------------------
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
                    log_fn(f"  [Math OCR] {model} hit {err_type}. Retrying in {wait_sec}s (retry {attempt + 1}/{len(delays)})...")
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
                log_fn(f"  [Math OCR Fallback] {model_name} still unavailable (503). Falling back to {fallback_model}...")
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
    chunks = [images[i:i + chunk_size] for i in range(0, len(images), chunk_size)]
    transcriptions = []
    used_model = model_name

    for c_idx, chunk in enumerate(chunks):
        if c_idx > 0:
            if log_fn:
                log_fn("  [Math OCR] Pausing 15s between image chunks to respect rate limits...")
            time.sleep(15)

        contents = [WHITEBOARD_OCR_PROMPT]
        for item in chunk:
            idx = item.get("num", 1)
            part = _genai_types.Part.from_bytes(
                data=item["bytes"],
                mime_type=item.get("mime") or "image/jpeg"
            )
            contents.append(f"Image {idx}:")
            contents.append(part)

        if log_fn:
            chunk_desc = f"Image {chunk[0].get('num', 1)}" if len(chunk) == 1 else f"Images {chunk[0].get('num', 1)}-{chunk[-1].get('num', len(chunk))}"
            log_fn(f"  [Math OCR] Transcribing {chunk_desc} ({len(chunk)} image(s)) with {used_model}...")

        response, chunk_model = _generate_content_with_retry(client, used_model, contents, log_fn=log_fn)
        used_model = chunk_model

        text = (response.text or "").strip()
        text = re.sub(r"^```(?:latex|tex)?\s*\n?", "", text, flags=re.I)
        text = re.sub(r"\n?```$", "", text)
        if text.strip():
            transcriptions.append(text.strip())

    return "\n\n".join(transcriptions), used_model


def transcribe_whiteboard_image(img_bytes: bytes, mime_type: str, api_key: str, model_name: str = "gemini-3.5-flash-lite", log_fn=None) -> str:
    """Transcribes a math whiteboard image into clean LaTeX using Gemini Vision."""
    text, _ = transcribe_whiteboard_images(
        [{"bytes": img_bytes, "mime": mime_type, "num": 1}],
        api_key=api_key,
        model_name=model_name,
        log_fn=log_fn
    )
    return text


def collect_page_images(blocks):
    """Collects all image blocks from a block tree in order with their downloaded bytes and mime types."""
    image_entries = []
    for b in walk(blocks):
        if b.get("type") == "image":
            img = b.get("_img")
            d = b.get("image") or {}
            if not img:
                u = (d.get(d.get("type")) or {}).get("url", "")
                if u:
                    img = {"url": u, "n": len(image_entries) + 1}
                    b["_img"] = img
            if img:
                data = img.get("bytes")
                if not data and img.get("path") and os.path.exists(img["path"]):
                    try:
                        with open(img["path"], "rb") as f_in:
                            data = f_in.read()
                    except Exception:
                        pass
                if not data and img.get("url"):
                    try:
                        data, ctype = download(img["url"])
                        img["bytes"] = data
                        img["ext"] = detect_ext(img["url"], ctype, data)
                    except Exception:
                        pass
                if data:
                    ext = img.get("ext", ".png")
                    mime = MIME.get(ext, "image/jpeg") if ext else "image/jpeg"
                    image_entries.append({
                        "block": b,
                        "img": img,
                        "bytes": data,
                        "mime": mime,
                        "num": len(image_entries) + 1,
                    })
    return image_entries


_TEX_MAP = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}
_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]")


def escape_tex(s: str) -> str:
    """Escape LaTeX specials in ONE pass (a sequential replace would re-escape the braces
    of \\textbackslash{}) and drop emoji, which pdflatex cannot typeset."""
    if not s:
        return ""
    s = _EMOJI_RE.sub("", s)
    return re.sub(r"[\\&%$#_{}~^]", lambda m: _TEX_MAP[m.group()], s)


def rt_tex(rts, r):
    out = []
    for x in rts or []:
        a = x.get("annotations", {})
        if x.get("type") == "equation":
            s = f"${x['equation']['expression']}$"
        else:
            raw = x.get("plain_text", "")
            s = escape_tex(raw).replace("\n", " ")
        if a.get("code"):
            s = f"\\texttt{{{s}}}"
        if a.get("bold"):
            s = f"\\textbf{{{s}}}"
        if a.get("italic"):
            s = f"\\textit{{{s}}}"
        if a.get("strikethrough"):
            s = f"\\sout{{{s}}}"
        if a.get("underline"):
            s = f"\\underline{{{s}}}"
        href = x.get("href")
        if href and r.keep_link(href):
            safe_href = href.replace("%", "\\%").replace("#", "\\#")
            s = f"\\href{{{safe_href}}}{{{s}}}"
        out.append(s)
    return "".join(out)


def props_tex(rows, layout: str) -> str:
    if not rows or layout == "Hidden":
        return ""
    if layout == "Notion Table":
        rows_tex = "".join(f"  \\textbf{{{escape_tex(k)}}} & {escape_tex(v)} \\\\\n  \\hline\n" for k, v in rows)
        return (
            "\\begin{center}\n"
            "\\begin{tabular}{|r|l|}\n"
            "  \\hline\n"
            f"{rows_tex}"
            "\\end{tabular}\n"
            "\\end{center}\n\\medskip\n\n"
        )
    if layout == "Inline Pills":
        pills = " \\quad ".join(f"\\textbf{{{escape_tex(k)}:}} {escape_tex(v)}" for k, v in rows)
        return f"\\noindent {pills}\n\\par\\medskip\n\n"
    if layout == "Minimalist List":
        items = "".join(f"  \\item[\\textbf{{{escape_tex(k)}}}] {escape_tex(v)}\n" for k, v in rows)
        return f"\\begin{{description}}\n{items}\\end{{description}}\n\\medskip\n\n"
    return ""


def blocks_tex(blocks, r, it, base_dir, log_fn=None, img_counter=None, page_ocr=None):
    if img_counter is None:
        img_counter = [0]
    out, i = [], 0
    cfg = r.cfg

    if page_ocr is None and cfg.get("gemini_math_ocr"):
        page_tree = getattr(it, "tree", None) or blocks
        page_images = collect_page_images(page_tree)
        if page_images:
            key = cfg.get("gemini_api_key", "").strip()
            model = cfg.get("gemini_model", "gemini-3.5-flash-lite")
            if log_fn:
                log_fn(f"  [Math OCR] Found {len(page_images)} whiteboard image(s) on page. Starting single multimodal transcription...")
            try:
                transcription, used_model = transcribe_whiteboard_images(page_images, key, model, log_fn)
                page_ocr = {
                    "text": transcription,
                    "model": used_model,
                    "error": None,
                    "emitted": False,
                }
            except Exception as err:
                if log_fn:
                    log_fn(f"  [Math OCR Error] {err}")
                page_ocr = {
                    "text": "",
                    "model": model,
                    "error": str(err),
                    "emitted": False,
                }
        else:
            page_ocr = {"text": "", "model": "", "error": None, "emitted": False}

    while i < len(blocks):
        b = blocks[i]
        t = b["type"]
        if t in LIST_TYPES:
            env = "enumerate" if t == "numbered_list_item" else "itemize"
            items = []
            while i < len(blocks) and blocks[i]["type"] == t:
                bb = blocks[i]
                d = bb[t]
                inner = rt_tex(d.get("rich_text"), r)
                if t == "to_do":
                    chk = "$\\boxtimes$" if d.get("checked") else "$\\square$"
                    inner = f"[{chk}] {inner}"
                else:
                    inner = f" {inner}"
                kids_tex = blocks_tex(bb.get("children", []), r, it, base_dir, log_fn, img_counter, page_ocr)
                items.append(f"  \\item{inner}\n{kids_tex}")
                i += 1
            out.append(f"\\begin{{{env}}}\n{''.join(items)}\\end{{{env}}}\n")
            continue

        d = b.get(t) or {}
        kids = b.get("children", [])

        def sub():
            return blocks_tex(kids, r, it, base_dir, log_fn, img_counter, page_ocr)

        if t == "paragraph":
            p = rt_tex(d.get("rich_text"), r)
            if p.strip():
                out.append(f"{p}\\par\\medskip\n{sub()}")
            elif kids:
                out.append(sub())
        elif t == "heading_1":
            h = rt_tex(d.get("rich_text"), r)
            out.append(f"\\section*{{{h}}}\n{sub()}")
        elif t == "heading_2":
            h = rt_tex(d.get("rich_text"), r)
            out.append(f"\\subsection*{{{h}}}\n{sub()}")
        elif t == "heading_3":
            h = rt_tex(d.get("rich_text"), r)
            out.append(f"\\subsubsection*{{{h}}}\n{sub()}")
        elif t == "quote":
            q = rt_tex(d.get("rich_text"), r)
            out.append(f"\\begin{{quote}}\n{q}\n{sub()}\\end{{quote}}\n")
        elif t == "callout":
            ic = d.get("icon") or {}
            emoji = ic.get("emoji", "") if ic.get("type") == "emoji" else ""
            prefix = f"\\textbf{{{escape_tex(emoji)}}} " if emoji else ""
            c_text = rt_tex(d.get("rich_text"), r)
            out.append(f"\\begin{{quote}}\n{prefix}{c_text}\n{sub()}\\end{{quote}}\n")
        elif t == "code":
            raw_code = plain(d.get("rich_text"))
            cap = plain(d.get("caption"))
            cap_line = f"\n% Caption: {cap}" if cap else ""
            out.append(f"\\begin{{verbatim}}{cap_line}\n{raw_code}\n\\end{{verbatim}}\n")
        elif t == "divider":
            out.append("\\noindent\\rule{\\linewidth}{0.4pt}\\par\\medskip\n")
        elif t == "equation":
            expr = d.get("expression", "")
            out.append(f"\\begin{{equation*}}\n{expr}\n\\end{{equation*}}\n")
        elif t == "table":
            rows = [x for x in kids if x["type"] == "table_row"]
            if rows:
                col_count = max(len(row["table_row"]["cells"]) for row in rows)
                spec = "|" + "l|" * col_count
                t_lines = [f"\\begin{{center}}\n\\begin{{tabular}}{{{spec}}}\n\\hline"]
                for row in rows:
                    cells = [rt_tex(c, r) for c in row["table_row"]["cells"]]
                    cells += [""] * (col_count - len(cells))
                    t_lines.append(" & ".join(cells) + " \\\\\n\\hline")
                t_lines.append("\\end{tabular}\n\\end{center}\n")
                out.append("\n".join(t_lines))
        elif t == "image":
            img = b.get("_img")
            img_counter[0] += 1
            cur_img_num = img_counter[0]
            if not img:
                u = (d.get(d.get("type")) or {}).get("url", "")
                if u:
                    img = {"url": u, "n": cur_img_num}

            if page_ocr and not page_ocr.get("emitted"):
                page_ocr["emitted"] = True
                if page_ocr.get("text"):
                    out.append(
                        f"\n% --- Transcribed Math Whiteboard (Gemini OCR: {page_ocr['model']}) ---\n"
                        f"{page_ocr['text']}\n"
                        f"% --- End Transcribed Math ---\n\n"
                    )
                elif page_ocr.get("error"):
                    out.append(f"\n% [Math OCR Failed on lecture images: {escape_tex(page_ocr['error'])}]\n")

            if page_ocr and page_ocr.get("text") and not cfg.get("keep_whiteboard_image"):
                i += 1
                continue

            if LATEX_IMAGES_AS_COMMENTS:
                nm = os.path.basename(unquote(urlparse((img or {}).get("url", "")).path)) or "image"
                out.append(f"% [Image {cur_img_num} omitted: {nm.replace(chr(10), ' ')}]\n")
                i += 1
                continue

            img_path = img.get("path") if img else None
            if img_path and os.path.splitext(img_path)[1].lower() not in (".png", ".jpg", ".jpeg", ".pdf"):
                out.append(f"% [Image format not supported by LaTeX, convert to PNG/JPG: {os.path.basename(img_path)}]\n")
            elif img_path and os.path.exists(img_path):
                rel_path = os.path.relpath(img_path, base_dir).replace("\\", "/")
                cap = plain(d.get("caption"))
                if not cap and cfg.get("show_image_names"):
                    cap = _build_caption(cfg.get("caption_format", "{name}"), img, cur_img_num)
                cap_tex = f"\\caption{{{escape_tex(cap)}}}" if cap else ""
                fig_tex = (
                    "\\begin{figure}[htbp]\n"
                    "\\centering\n"
                    f"\\includegraphics[width=0.85\\linewidth]{{{rel_path}}}\n"
                    f"{cap_tex}\n"
                    "\\end{figure}\n\n"
                )
                out.append(fig_tex)
            elif img and img.get("url"):
                out.append(f"% [Image: {img.get('url')}]\n")
        elif t in ("video", "file", "pdf", "audio"):
            src = d.get(d.get("type")) or {}
            name = plain(d.get("caption")) or d.get("name") or "Attachment"
            out.append(f"\\texttt{{[Attachment: {escape_tex(name)}]}}\\par\\medskip\n")
        elif t in ("bookmark", "embed", "link_preview"):
            url = d.get("url", "")
            text = plain(d.get("caption")) or url
            if r.keep_link(url):
                safe_url = url.replace("%", "\\%").replace("#", "\\#")
                out.append(f"\\href{{{safe_url}}}{{{escape_tex(text)}}}\\par\\medskip\n")
            else:
                out.append(f"{escape_tex(text)}\\par\\medskip\n")
        elif t == "child_page":
            s = b.get("_sub")
            if s:
                out.append(f"\\subsection*{{{escape_tex(s['title'])}}}\n" +
                           blocks_tex(s["tree"], r, it, base_dir, log_fn, img_counter, page_ocr))
            else:
                out.append(f"\\textit{{[Child Page: {escape_tex(d.get('title', ''))}]}}\\par\\medskip\n")
        elif t in ("column_list", "column", "synced_block"):
            out.append(sub())
        elif "rich_text" in d:
            t_str = rt_tex(d.get("rich_text"), r)
            if t_str.strip():
                out.append(f"{t_str}\\par\\medskip\n{sub()}")
            elif kids:
                out.append(sub())

        i += 1
    return "".join(out)


def build_complete_latex(title: str, prop_rows: list, body_tex: str, cfg: dict) -> str:
    """Wraps body LaTeX in a clean, complete, compilable LaTeX article document."""
    escaped_title = escape_tex(title)
    props_block = props_tex(prop_rows, cfg.get("prop_layout", "Notion Table"))
    cover_page_break = "\\newpage\n\n" if cfg.get("cover_page") else ""

    doc = [
        "\\documentclass[11pt,a4paper]{article}",
        "% Compile with pdflatex (Latin text). For Arabic/CJK use xelatex or lualatex.",
        "\\usepackage[utf8]{inputenc}",
        "\\usepackage[T1]{fontenc}",
        "\\usepackage[margin=1in]{geometry}",
        "\\usepackage{amsmath,amssymb,amsthm}",
        "\\usepackage{graphicx}",
        "\\usepackage[normalem]{ulem}",
        "\\usepackage{xcolor}",
        "\\usepackage{hyperref}",
        "",
        "\\hypersetup{",
        "    colorlinks=true,",
        "    linkcolor=blue,",
        "    filecolor=magenta,",
        "    urlcolor=blue,",
        f"    pdftitle={{{escaped_title}}},",
        "}",
        "",
        f"\\title{{{escaped_title}}}",
        "\\author{}",
        "\\date{\\today}",
        "",
        "\\begin{document}",
        "\\maketitle",
        "",
        props_block,
        cover_page_break,
        body_tex,
        "\\end{document}",
        "",
    ]
    return "\n".join(doc)


# ----------------------------------------------------------------------
# Browser / PDF
# ----------------------------------------------------------------------
STEALTH_ARGS = ["--disable-blink-features=AutomationControlled"]


_PAINT_RE = re.compile(rb"(?<![A-Za-z0-9_/.\-])(?:f\*?|F|S|s|B\*?|b\*?|sh|Do|Tj|TJ)(?![A-Za-z0-9_])")


def _page_is_blank(page):
    """True when a PDF page has no text, no images and nothing painted."""
    try:
        if (page.extract_text() or "").strip():
            return False
    except Exception:
        return False
    try:
        if len(page.images):
            return False
    except Exception:
        pass
    try:
        contents = page.get_contents()
        if contents is None:
            return True
        return not _PAINT_RE.search(contents.get_data())
    except Exception:
        return False


def remove_blank_pages(path):
    """Delete empty pages from a PDF file in place. Returns how many were removed."""
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        from PyPDF2 import PdfReader, PdfWriter
    reader = PdfReader(path)
    keep = [i for i, pg in enumerate(reader.pages) if not _page_is_blank(pg)]
    removed = len(reader.pages) - len(keep)
    if not keep or removed == 0:
        return 0
    w = PdfWriter()
    for i in keep:
        w.add_page(reader.pages[i])
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        w.write(f)
    os.replace(tmp, path)
    return removed


class Cancelled(Exception):
    pass


class LoginRequired(Exception):
    pass


BASE_CSS  = """
@media print {
  html, body, .notion-app-inner, .notion-frame, .notion-scroller,
  .notion-page-content { height: auto !important; overflow: visible !important; }
}
"""
CLEAN_CSS = """
.notion-topbar, .notion-topbar-mobile, .notion-sidebar-container,
.notion-help-button, .notion-overlay-container { display: none !important; }
"""
EXPAND_JS = """() => {
  const b = [...document.querySelectorAll(
    '.notion-page-content [role="button"][aria-expanded="false"]')];
  b.forEach(x => x.click());
  return b.length;
}"""
SCROLL_JS = """async () => {
  const sc = [...document.querySelectorAll('.notion-scroller')]
    .filter(e => e.scrollHeight > e.clientHeight);
  for (const s of sc) {
    for (let y = 0; y < s.scrollHeight; y += 700) {
      s.scrollTop = y;
      await new Promise(r => setTimeout(r, 120));
    }
    s.scrollTop = 0;
  }
}"""
IMAGES_JS = """async () => {
  const imgs = [...document.images].filter(i => !i.complete);
  await Promise.race([
    Promise.all(imgs.map(i => new Promise(r => { i.onload = i.onerror = r; }))),
    new Promise(r => setTimeout(r, 15000))
  ]);
}"""
HIDE_PROPS_JS = """(args) => {
  const hide = args.hide, allSet = new Set(args.all);
  const content = document.querySelector('.notion-page-content');
  const leaves = [...document.querySelectorAll('div,span')].filter(e =>
    e.children.length === 0 && allSet.has(e.textContent.trim()) &&
    !(content && content.contains(e)));
  for (const leaf of leaves) {
    if (!hide.includes(leaf.textContent.trim())) continue;
    let el = leaf;
    for (let i = 0; i < 6 && el.parentElement; i++) {
      const parent = el.parentElement;
      const other = leaves.some(o => o !== leaf && parent.contains(o) && !el.contains(o));
      if (other) { el.style.display = 'none'; break; }
      el = parent;
    }
  }
}"""
LINKS_JS = """(mode) => document.querySelectorAll('a[href]').forEach(a => {
  const h = a.getAttribute('href') || '';
  const internal = h.startsWith('/') || /^https?:\\/\\/(www\\.)?notion\\.(so|site)/.test(h);
  if (mode === 'all' || (mode === 'internal' && internal)) a.removeAttribute('href');
})"""


def _pagenum_templates(cfg: dict):
    """Return (header_template, footer_template) based on position/format settings."""
    pos = cfg.get("page_num_position", PAGENUM_POS[0])
    fmt = cfg.get("page_num_format", PAGENUM_FMT[0])

    if fmt == "Page X of Y":
        content = ('<span style="font-size:9px;color:#666">'
                   'Page <span class="pageNumber"></span>'
                   ' of <span class="totalPages"></span></span>')
    else:
        content = ('<span style="font-size:9px;color:#666">'
                   '<span class="pageNumber"></span></span>')

    align_map = {
        "Bottom Center": "center",
        "Bottom Right":  "right",
        "Top Right":     "right",
    }
    align = align_map.get(pos, "center")
    wrapped = f'<div style="width:100%;text-align:{align}">{content}</div>'

    if pos == "Top Right":
        return wrapped, "<span></span>"
    return "<span></span>", wrapped


def pdf_kwargs(cfg, path):
    m      = f"{int(cfg['margin_mm'])}mm"
    margin = {"top": m, "bottom": m, "left": m, "right": m}
    kw     = dict(path=path, format=cfg["page_size"],
                  landscape=(cfg["orientation"] == "Landscape"),
                  print_background=bool(cfg["print_background"]),
                  scale=max(0.1, min(2.0, float(cfg["scale"]) / 100)))
    if cfg["page_numbers"]:
        pos = cfg.get("page_num_position", PAGENUM_POS[0])
        if pos == "Top Right":
            margin["top"] = f"{max(int(cfg['margin_mm']), 15)}mm"
        else:
            margin["bottom"] = f"{max(int(cfg['margin_mm']), 15)}mm"
        hdr, ftr = _pagenum_templates(cfg)
        kw.update(display_header_footer=True, header_template=hdr, footer_template=ftr)
    kw["margin"] = margin
    return kw


def launch_context(pw, cfg, headless=True):
    scheme   = "light" if cfg.get("light_theme", True) else "no-preference"
    viewport = {"width": 1280, "height": 1000}
    if cfg.get("use_login", True):
        os.makedirs(PROFILE_DIR, exist_ok=True)
        ctx = pw.chromium.launch_persistent_context(
            PROFILE_DIR, headless=headless, color_scheme=scheme, viewport=viewport,
            args=STEALTH_ARGS, ignore_default_args=["--enable-automation"])
        return None, ctx
    browser = pw.chromium.launch(headless=headless)
    return browser, browser.new_context(color_scheme=scheme, viewport=viewport)


def login_to_notion(log):
    """Opens a visible browser; log in, then close the window."""
    cfg = dict(DEFAULTS)
    cfg["use_login"] = True
    with sync_playwright() as pw:
        _, ctx = launch_context(pw, cfg, headless=False)
        page   = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.notion.so/login")
        log("Log in to Notion in the browser window, then close the window.")
        try:
            while True:
                page.wait_for_timeout(1000)
        except Exception:
            pass
        try:
            ctx.close()
        except Exception:
            pass
    log("Login session saved.")


def render_notion_page(page, pid, path, cfg, all_props, hide_names):
    """Browser engine: print the real Notion page."""
    page.goto(f"https://www.notion.so/{pid.replace('-', '')}",
              wait_until="domcontentloaded", timeout=60000)
    if "/login" in page.url:
        raise LoginRequired()
    page.wait_for_selector(".notion-page-content", timeout=45000)
    page.wait_for_timeout(1000)
    if cfg["expand_toggles"]:
        for _ in range(8):
            if not page.evaluate(EXPAND_JS):
                break
            page.wait_for_timeout(600)
    page.evaluate(SCROLL_JS)
    page.evaluate(IMAGES_JS)
    page.wait_for_timeout(int(float(cfg["extra_wait"]) * 1000))
    css = BASE_CSS + (CLEAN_CSS if cfg["clean_layout"] else "") + (cfg.get("custom_css") or "")
    page.add_style_tag(content=css)
    if hide_names:
        page.evaluate(HIDE_PROPS_JS, {"hide": hide_names, "all": all_props})
    mode = {LINK_MODES[1]: "all", LINK_MODES[2]: "internal"}.get(cfg["links"])
    if mode:
        page.evaluate(LINKS_JS, mode)
    page.pdf(**pdf_kwargs(cfg, path))


# ----------------------------------------------------------------------
# Export engine
# ----------------------------------------------------------------------
class Item:
    def __init__(self, id, page, title, parent=None, depth=0, created="", edited=""):
        self.id, self.page, self.title = id, page, title or "Untitled"
        self.parent, self.depth = parent, depth
        self.created, self.edited = created, edited
        self.tree, self.imgs = None, []
        self.base, self.dirparts, self.fields = "", [], {}

    @property
    def label(self):
        return "/".join(self.dirparts + [self.base])


class Exporter:
    def __init__(self, cfg, all_props=None, shown_props=None, log=print,
                 progress=lambda i, n: None, cancel=None, notion=None):
        self.cfg        = cfg
        self.all_props  = list(all_props or [])
        self.shown_props= list(shown_props or [])
        self.log, self.progress = log, progress
        self.cancel     = cancel or threading.Event()
        self.notion     = notion or Client(auth=cfg["token"])
        self.cache      = {}
        self.used_paths = set()
        self.failed     = []
        self.last_tex   = ""
        self._tex_body  = ""
        self._lock      = threading.Lock()

    # ---- sources ----
    def fetch_roots(self):
        c     = self.cfg
        roots = resolve_roots(self.notion, c["database"], c["source_type"])
        roots = [p for p in roots if passes_filter(p, c["filter_prop"], c["filter_op"], c["filter_value"])]
        roots = sort_pages(roots, c["sort_by"], c["sort_desc"])
        if int(c["max_pages"]) > 0:
            roots = roots[:int(c["max_pages"])]
        return roots

    def tree_of(self, it):
        if it.tree is None:
            it.tree = build_tree(self.notion, it.id, self.cache)
        return it.tree

    def plan(self, roots):
        c        = self.cfg
        items    = []
        separate = c["sub_mode"] == SUB_MODES[2]
        maxdepth = int(c["sub_depth"])

        def expand(it):
            if not separate or it.depth >= maxdepth:
                return
            for b in walk(self.tree_of(it), subs=False):
                t = b["type"]
                if t == "child_page":
                    sub = Item(b["id"], None, b["child_page"].get("title"), it, it.depth + 1,
                               b.get("created_time", "")[:10], b.get("last_edited_time", "")[:10])
                    items.append(sub)
                    expand(sub)
                elif t == "child_database" and c["sub_dbs"]:
                    try:
                        rows = query_all(self.notion, b["id"])
                    except Exception as e:
                        self.failed.append((b["child_database"].get("title", "database"), str(e)[:80]))
                        continue
                    for row in rows:
                        sub = Item(row["id"], row, page_title(row), it, it.depth + 1)
                        items.append(sub)
                        expand(sub)

        if separate:
            self.log("Scanning for sub-pages...")
        for p in roots:
            it = Item(p["id"], p, page_title(p))
            items.append(it)
            expand(it)

        pad     = max(2, len(str(len(items))))
        counter = defaultdict(int)
        for idx, it in enumerate(items, 1):
            if it.page:
                f = page_fields(it.page, idx, pad)
            else:
                f = {"title": it.title, "date": "", "created": it.created, "edited": it.edited,
                     "index": f"{idx:0{pad}d}"}
            f["parent"] = it.parent.title if it.parent else ""
            it.fields   = f
            base        = build_name(c["name_format"], f)
            it.dirparts = (it.parent.dirparts + [it.parent.base]) if it.parent else []
            key         = (tuple(it.dirparts), base.lower())
            counter[key] += 1
            it.base     = f"{base} ({counter[key]:02})" if counter[key] > 1 else base
        return items

    # ---- paths ----
    def target(self, fmt, it):
        folder = os.path.join(self.cfg["save_dir"], FOLDERS[fmt], *it.dirparts)
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, it.base + EXTS[fmt])

    # ---- images ----
    def image_path(self, it, img, data):
        c = self.cfg
        f = dict(it.fields)
        f["page"]     = it.base
        f["n"]        = img["n"] if img["n"] == "cover" else f"{img['n']:02d}"
        f["caption"]  = clean_filename(img.get("caption", ""))[:60]
        f["original"] = os.path.splitext(os.path.basename(unquote(urlparse(img["url"]).path)))[0]
        name   = build_name(c["img_format"], f)
        folder = os.path.join(c["save_dir"], "Images")
        if c["img_subfolder"]:
            folder = os.path.join(folder, *it.dirparts, it.base)
        os.makedirs(folder, exist_ok=True)
        with self._lock:
            path = os.path.join(folder, name + img["ext"])
            k = 2
            while path.lower() in self.used_paths:
                path = os.path.join(folder, f"{name} ({k:02d}){img['ext']}")
                k += 1
            self.used_paths.add(path.lower())
        return path

    def _optimize(self, img):
        """Shrink big photos for PDF/Word embedding (much faster + smaller files)."""
        c = self.cfg
        if not c.get("optimize_images", True) or img.get("ext") in (".svg", ".gif"):
            return
        try:
            from PIL import Image, ImageOps
            mx = int(c.get("image_max_px", 1600))
            im = Image.open(io.BytesIO(img["bytes"]))
            if max(im.size) <= mx and len(img["bytes"]) < 400_000:
                return
            im = ImageOps.exif_transpose(im)
            im.thumbnail((mx, mx), Image.LANCZOS)
            buf = io.BytesIO()
            if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
                im.convert("RGBA").save(buf, "PNG", optimize=True)
                mime = "image/png"
            else:
                im.convert("RGB").save(buf, "JPEG", quality=85, optimize=True)
                mime = "image/jpeg"
            if len(buf.getvalue()) < len(img["bytes"]):
                img["opt_bytes"], img["opt_mime"] = buf.getvalue(), mime
        except Exception:
            pass

    def prepare_images(self, it):
        c          = self.cfg
        handling   = c["img_handling"]
        engine_api = c["engine"] == ENGINES[0]
        tex_files  = c.get("fmt_tex", False) and not LATEX_IMAGES_AS_COMMENTS
        save_files = c["fmt_images"] or handling == IMG_MODES[1] or tex_files or \
            (handling == IMG_MODES[0] and c["fmt_md"])
        embed_pdf  = c["fmt_pdf"] and engine_api and handling == IMG_MODES[0]
        need_bytes = save_files or c["fmt_docx"] or c.get("gemini_math_ocr", False) or embed_pdf or \
            (handling == IMG_MODES[0] and c["fmt_html"])
        if not need_bytes:
            return
        imgs = []
        if c["img_cover"] and it.page and it.page.get("cover"):
            cv  = it.page["cover"]
            url = (cv.get(cv.get("type")) or {}).get("url")
            if url:
                imgs.append({"url": url, "caption": "", "n": "cover"})
        n = 0
        for b in walk(it.tree or []):
            if b["type"] == "image":
                d   = b["image"]
                url = (d.get(d.get("type")) or {}).get("url")
                if not url:
                    continue
                n  += 1
                img = {"url": url, "caption": plain(d.get("caption")), "n": n}
                b["_img"] = img
                imgs.append(img)
        want_opt = embed_pdf or c["fmt_docx"]

        def fetch(img):
            try:
                data, ctype = download(img["url"])
                img["bytes"], img["ext"] = data, detect_ext(img["url"], ctype, data)
                if want_opt:
                    self._optimize(img)
            except Exception as e:
                self.failed.append((f"{it.label} (image {img['n']})", str(e)[:80]))

        if imgs:
            with ThreadPoolExecutor(max_workers=min(8, len(imgs))) as ex:   # downloads in parallel
                list(ex.map(fetch, imgs))
        if save_files:
            for img in imgs:
                if "bytes" in img:
                    try:
                        path = self.image_path(it, img, img["bytes"])
                        with open(path, "wb") as f:
                            f.write(img["bytes"])
                        img["path"] = path
                    except Exception as e:
                        self.failed.append((f"{it.label} (image {img['n']})", str(e)[:80]))
        it.imgs = imgs

    # ---- content helpers ----
    def prop_rows(self, it):
        if not it.page:
            return []
        date_fmt = self.cfg.get("date_format_props", "YYYY-MM-DD")
        rows = []
        for k, v in it.page["properties"].items():
            if v["type"] == "title":
                continue
            if self.all_props and k not in self.shown_props:
                continue
            txt = prop_to_text(v, date_fmt)
            if txt:
                rows.append((k, txt))
        return rows

    def _page_icon_text(self, it) -> str:
        """Return the emoji/icon text for docx/md/txt (empty if hidden)."""
        mode = self.cfg.get("icon_mode", ICON_MODES[0])
        if mode == "Hide icon":
            return ""
        if it.page:
            icon = it.page.get("icon") or {}
            if icon.get("type") == "emoji":
                return icon["emoji"]
        return ""

    def body_html(self, it, kind, base_dir):
        r    = R(self.cfg, kind, base_dir)
        cfg  = self.cfg
        rows = self.prop_rows(it)
        layout = cfg.get("prop_layout", "Notion Table")

        # Page icon HTML
        icon_html = _page_icon_html(it.page, cfg)

        # Title
        sep_cls  = ""
        h = f'{icon_html}<h1 class="notion-title{sep_cls}">{esc(it.title)}</h1>'

        # Properties HTML
        h += props_html(rows, layout, cfg)

        # Cover page wrapper
        body_html = blocks_html(it.tree or [], r)
        if cfg.get("cover_page"):
            cover = f'<div class="notion-cover-page">{h}</div><div class="notion-page-break"></div>'
            return cover + body_html
        return h + body_html

    def text_md(self, it, base_dir):
        r    = R(self.cfg, "md", base_dir)
        body = "\n".join(blocks_md(it.tree or [], r))
        icon = self._page_icon_text(it)
        prefix = f"{icon} " if icon else ""
        return md_front_matter(it.title, self.prop_rows(it)) + f"\n\n# {prefix}{it.title}\n\n" + body + "\n"

    def text_txt(self, it):
        lines  = [it.title, "=" * len(it.title), ""]
        lines += [f"{k}: {v}" for k, v in self.prop_rows(it)]
        if len(lines) > 3:
            lines.append("")
        lines += blocks_txt(it.tree or [])
        return "\n".join(lines) + "\n"

    def text_tex(self, it, base_dir):
        r = R(self.cfg, "tex", base_dir)
        body = blocks_tex(it.tree or [], r, it, base_dir, self.log)
        self._tex_body = body
        return build_complete_latex(it.title, self.prop_rows(it), body, self.cfg)

    def _clean_pdf(self, path):
        if not self.cfg.get("remove_blank_pages", True):
            return
        try:
            n = remove_blank_pages(path)
            if n:
                self.log(f"  removed {n} blank page(s)")
        except Exception:
            pass

    # ---- pdf ----
    def pdf_browser(self, page, it, path, hide_names):
        for attempt in range(int(self.cfg["retries"]) + 1):
            try:
                render_notion_page(page, it.id, path, self.cfg, self.all_props, hide_names)
                return
            except LoginRequired:
                raise Exception("Notion asked for a login. Use 'Log in to Notion' on the Source "
                                "tab, sign in, close the window, then export again.")
            except Exception:
                if attempt >= int(self.cfg["retries"]):
                    raise
                self.log(f"retrying: {it.label}")

    def pdf_api(self, page, it, path, tmp):
        html = wrap_html(it.title, self.body_html(it, "pdf", None), self.cfg)
        hp   = os.path.join(tmp, f"{abs(hash(it.id))}.html")
        with open(hp, "w", encoding="utf-8") as f:
            f.write(html)
        page.goto(Path(hp).resolve().as_uri(), wait_until="load")
        try:   # fonts / math finished (max 8 s, so a missing internet connection never hangs)
            page.evaluate("Promise.race([document.fonts ? document.fonts.ready : 0,"
                          " new Promise(r => setTimeout(r, 8000))])")
        except Exception:
            pass
        page.pdf(**pdf_kwargs(self.cfg, path))
        try:
            os.remove(hp)
        except OSError:
            pass

    # ---- main ----
    def run(self, selected_roots=None):
        c       = self.cfg
        formats = [f for f in FORMATS if c["fmt_" + f]]
        if not formats and not c["fmt_images"]:
            raise Exception("Pick at least one export format.")
        if not c["save_dir"].strip():
            raise Exception("Choose an output folder.")
        use_api_pdf = c["engine"] == ENGINES[0]
        doc_formats = [f for f in formats if f != "pdf"]
        need_tree   = bool(doc_formats) or c["fmt_images"] or c["sub_mode"] != SUB_MODES[0] \
            or ("pdf" in formats and use_api_pdf)
        inline      = c["sub_mode"] == SUB_MODES[1]

        self.log("Reading pages...")
        roots = selected_roots or self.fetch_roots()
        if not roots:
            raise Exception("No pages matched.")
        items = self.plan(roots)
        total = len(items)
        self.log(f"Exporting {total} page(s) to: " +
                 ", ".join(FORMAT_LABELS[f] for f in formats + (["images"] if c["fmt_images"] else [])))

        workers = max(1, min(8, int(c.get("workers", 4))))
        set_api_concurrency(min(3, workers))
        prefetch_pool = ThreadPoolExecutor(max_workers=workers) if need_tree else None
        futs, window  = {}, workers * 2

        def prep(it):
            self.tree_of(it)
            if inline:
                attach_inline(self.notion, it.tree, self.cache, 1, int(c["sub_depth"]))
            self.prepare_images(it)

        def submit(k):
            if prefetch_pool and 1 <= k <= total:
                futs[k] = prefetch_pool.submit(prep, items[k - 1])

        for k in range(1, min(total, window) + 1):      # pages are fetched in the background
            submit(k)                                   # while the previous one is being rendered

        hide_names   = [n for n in self.all_props if n not in self.shown_props] if self.all_props else []
        made_pdfs, combined_html, combined_md, made_tex = [], [], [], []
        tmp = tempfile.mkdtemp(prefix="notion_export_")
        pw = browser = ctx = page = None
        try:
            if "pdf" in formats:
                pw             = sync_playwright().start()
                pcfg           = dict(c, use_login=bool(c["use_login"]) and not use_api_pdf)
                browser, ctx   = launch_context(pw, pcfg)
                page           = ctx.new_page()

            html_root = os.path.join(c["save_dir"], FOLDERS["html"])
            md_root   = os.path.join(c["save_dir"], FOLDERS["md"])
            tex_root  = os.path.join(c["save_dir"], FOLDERS["tex"])

            for i, it in enumerate(items, 1):
                if self.cancel.is_set():
                    raise Cancelled()
                self.progress(i - 1, total)
                try:
                    if need_tree:
                        fut = futs.pop(i)
                        submit(i + window)
                        fut.result()

                    for fmt in formats:
                        path = self.target(fmt, it)
                        if c["skip_existing"] and os.path.exists(path):
                            if fmt == "pdf":
                                made_pdfs.append((it.label, path))
                            continue
                        try:
                            if fmt == "pdf":
                                if use_api_pdf:
                                    self.pdf_api(page, it, path, tmp)
                                else:
                                    self.pdf_browser(page, it, path, hide_names)
                                self._clean_pdf(path)
                                made_pdfs.append((it.label, path))
                            elif fmt == "html":
                                body = self.body_html(it, "html", os.path.dirname(path))
                                with open(path, "w", encoding="utf-8") as f:
                                    f.write(wrap_html(it.title, body, c))
                            elif fmt == "md":
                                with open(path, "w", encoding="utf-8") as f:
                                    f.write(self.text_md(it, os.path.dirname(path)))
                            elif fmt == "txt":
                                with open(path, "w", encoding="utf-8") as f:
                                    f.write(self.text_txt(it))
                            elif fmt == "docx":
                                icon_text = self._page_icon_text(it)
                                build_docx(it.title, icon_text, self.prop_rows(it),
                                           it.tree or [], R(c, "docx"), path, c)
                            elif fmt == "json":
                                data = {"id": it.id, "title": it.title,
                                        "properties": (it.page or {}).get("properties", {}),
                                        "blocks": strip_private(it.tree or [])}
                                with open(path, "w", encoding="utf-8") as f:
                                    json.dump(data, f, ensure_ascii=False, indent=2, default=str)
                            elif fmt == "tex":
                                tex_code = self.text_tex(it, os.path.dirname(path))
                                with open(path, "w", encoding="utf-8") as f:
                                    f.write(tex_code)
                                made_tex.append((it.title, path, self._tex_body))
                                self.last_tex = tex_code
                        except LoginRequired:
                            raise
                        except Exception as e:
                            if "login" in str(e).lower() and fmt == "pdf":
                                raise
                            self.failed.append((f"{it.label} [{fmt}]",
                                                str(e).splitlines()[0][:100] if str(e) else "error"))
                            self.log(f"FAILED {fmt}: {it.label}")
                    if c["combine"]:
                        if c["fmt_html"]:
                            combined_html.append((it, self.body_html(it, "html", html_root)))
                        if c["fmt_md"]:
                            combined_md.append(self.text_md(it, md_root))
                    self.log(f"[{i}/{total}] {it.label}")
                    for im in it.imgs:                  # free memory early
                        im.pop("bytes", None)
                        im.pop("opt_bytes", None)
                except Cancelled:
                    raise
                except Exception as e:
                    if "asked for a login" in str(e):
                        raise
                    self.failed.append((it.label, str(e).splitlines()[0][:100] if str(e) else "error"))
                    self.log(f"[{i}/{total}] FAILED: {it.label}")
        finally:
            if prefetch_pool:
                prefetch_pool.shutdown(wait=False, cancel_futures=True)
            for obj in (ctx, browser):
                try:
                    if obj:
                        obj.close()
                except Exception:
                    pass
            if pw:
                try:
                    pw.stop()
                except Exception:
                    pass
            shutil.rmtree(tmp, ignore_errors=True)
        self.progress(total, total)

        name = clean_filename(c["merged_name"]) or "All_Pages"
        if combined_html:
            toc  = "".join(f'<li><a href="#p{n}">{esc(it.title)}</a></li>'
                           for n, (it, _) in enumerate(combined_html))
            secs = "".join(f'<section class="page" id="p{n}">{b}</section>'
                           for n, (_, b) in enumerate(combined_html))
            with open(os.path.join(html_root, name + ".html"), "w", encoding="utf-8") as f:
                f.write(wrap_html(name, f"<h1 class='notion-title'>{esc(name)}</h1><ol>{toc}</ol>{secs}", c))
        if combined_md:
            with open(os.path.join(md_root, name + ".md"), "w", encoding="utf-8") as f:
                f.write("\n\n---\n\n".join(combined_md))
        if made_tex and c["combine"]:
            combined_tex_sections = []
            for it_title, _, body_code in made_tex:
                combined_tex_sections.append(f"\\clearpage\n\\section{{{escape_tex(it_title)}}}\n\n" + body_code)
            with open(os.path.join(tex_root, name + ".tex"), "w", encoding="utf-8") as f:
                f.write(build_complete_latex(name, [], "\n\n".join(combined_tex_sections), c))

        if made_pdfs and c["output_mode"] != OUTPUT_MODES[2]:
            self.log("Merging PDFs...")
            merger = PdfMerger()
            for title, path in made_pdfs:
                try:
                    merger.append(path, outline_item=title if c["bookmarks"] else None)
                except Exception as e:
                    self.failed.append((title + " [merge]", str(e)[:80]))
            out = os.path.join(c["save_dir"], name + ".pdf")
            merger.write(out)
            merger.close()
            if c["output_mode"] == OUTPUT_MODES[1]:
                for _, path in made_pdfs:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                for dp, _, _ in os.walk(os.path.join(c["save_dir"], FOLDERS["pdf"]), topdown=False):
                    try:
                        os.rmdir(dp)
                    except OSError:
                        pass
        return c["save_dir"], total, self.failed


# ----------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------
class ScrollFrame(ttk.Frame):
    """A vertically scrollable page. Mouse-wheel routing is done globally by App._on_wheel."""

    def __init__(self, parent):
        super().__init__(parent)
        bg = ttk.Style().lookup("TFrame", "background") or "#f0f0f0"
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, bg=bg, yscrollincrement=20)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.canvas._wheel_canvas = self.canvas


class CheckList(ttk.Frame):
    """A scrollable list with a checkbox in front of every row."""

    def __init__(self, parent, height=190, empty_text="Nothing loaded yet."):
        super().__init__(parent)
        self.empty_text = empty_text
        self.canvas = tk.Canvas(self, height=height, highlightthickness=1, highlightbackground="#c4c4c4",
                                bg="white", yscrollincrement=20)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg="white")
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.canvas._wheel_canvas = self.canvas
        self.vars, self.labels = [], []
        self.info = tk.StringVar()
        self.set_items([])

    def _update(self, *_):
        n = sum(1 for v in self.vars if v.get())
        self.info.set(f"{n} of {len(self.vars)} selected" if self.vars else "")

    def set_items(self, labels, checked=True):
        for w in self.inner.winfo_children():
            w.destroy()
        self.vars, self.labels = [], list(labels)
        if not labels:
            tk.Label(self.inner, text=self.empty_text, bg="white", fg="#888888",
                     anchor="w").pack(fill="x", padx=8, pady=8)
        for lab in labels:
            v = tk.BooleanVar(value=checked)
            v.trace_add("write", self._update)
            self.vars.append(v)
            tk.Checkbutton(self.inner, text=lab, variable=v, bg="white", activebackground="#eaf2ff",
                           anchor="w", justify="left", relief="flat", borderwidth=0).pack(
                fill="x", padx=4, pady=0)
        self.canvas.yview_moveto(0)
        self._update()

    def select_all(self, flag=True):
        for v in self.vars:
            v.set(flag)

    def selected_indices(self):
        return [i for i, v in enumerate(self.vars) if v.get()]

    def selected_labels(self):
        return [self.labels[i] for i in self.selected_indices()]


_GENERIC_FONT_ALIAS = {"Sans-serif": "Helvetica", "Serif": "Times", "Monospace": "Courier"}


class FontPicker(tk.Toplevel):
    """Font chooser where every font name is shown in its own typeface."""

    SAMPLE = "The quick brown fox 0123456789  —  مرحبا بالعالم"

    def __init__(self, app, current, allow_same, on_pick):
        super().__init__(app.root)
        self.app, self.on_pick, self.current = app, on_pick, current
        self.title("Choose a font")
        self.geometry("500x600")
        self.transient(app.root)
        self.entries = []                     # (name or None, display)
        names = ([SAME_AS_BODY] if allow_same else []) + ["Sans-serif", "Serif", "Monospace"]
        self.sections = [("Generic", names)]
        cat = [n for n, _, _ in FONT_CATALOG]
        self.sections.append(("Recommended  (grey = not installed on this PC; Google Fonts need the option in the Design tab)", cat))
        self.sections.append(("Installed on this PC", [f for f in app.font_values if f not in cat
                                                      and f not in _GENERIC_FONT_ALIAS]))
        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(top, text="Search:").pack(side="left")
        self.q = tk.StringVar()
        ent = ttk.Entry(top, textvariable=self.q)
        ent.pack(side="left", fill="x", expand=True, padx=6)
        ent.focus_set()
        self.q.trace_add("write", lambda *_: self.fill())
        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, padx=10, pady=4)
        self.txt = tk.Text(mid, wrap="none", cursor="arrow", bg="white", relief="solid", borderwidth=1,
                           spacing1=3, spacing3=3)
        sb = ttk.Scrollbar(mid, command=self.txt.yview)
        self.txt.config(yscrollcommand=sb.set)
        self.txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.txt.tag_configure("head", font=("", 9, "bold"), foreground="#6b7280", spacing1=8)
        self.txt.tag_configure("pick", background="#cfe3ff")
        self.txt.tag_configure("web", foreground="#8a8f98")
        self.txt.bind("<Button-1>", self.on_click)
        self.txt.bind("<Double-Button-1>", lambda e: (self.on_click(e), self.use()))
        self.preview = tk.Label(self, text=self.SAMPLE, bg="white", relief="solid", borderwidth=1,
                                height=2, wraplength=470)
        self.preview.pack(fill="x", padx=10, pady=4)
        bt = ttk.Frame(self)
        bt.pack(fill="x", padx=10, pady=(2, 10))
        ttk.Button(bt, text="Use this font", command=self.use).pack(side="right")
        ttk.Button(bt, text="Cancel", command=self.destroy).pack(side="right", padx=6)
        self.chosen = current
        self.fill()
        self.grab_set()

    def family_for(self, name):
        fam = _GENERIC_FONT_ALIAS.get(name, name)
        return fam if (fam in self.app.installed or fam in _GENERIC_FONT_ALIAS.values()) else None

    def fill(self):
        q = self.q.get().strip().lower()
        t = self.txt
        t.config(state="normal")
        t.delete("1.0", "end")
        self.lines = {}
        n = 0
        for title, items in self.sections:
            items = [x for x in items if q in x.lower()]
            if not items:
                continue
            t.insert("end", title + "\n", "head")
            for name in items:
                tag = "f%d" % n
                n += 1
                fam = self.family_for(name)
                if fam:
                    t.tag_configure(tag, font=(fam, 13))
                    t.insert("end", "  " + name + "\n", tag)
                else:
                    t.tag_configure(tag, font=("", 11))
                    t.insert("end", "  " + name + "\n", (tag, "web"))
                self.lines[int(t.index("end-2l").split(".")[0])] = name
        t.config(state="disabled")
        self.mark()

    def mark(self):
        self.txt.tag_remove("pick", "1.0", "end")
        for ln, name in self.lines.items():
            if name == self.chosen:
                self.txt.tag_add("pick", f"{ln}.0", f"{ln}.end+1c")
                self.txt.see(f"{ln}.0")
        fam = self.family_for(self.chosen) if self.chosen else None
        self.preview.config(font=(fam, 15) if fam else ("", 12))

    def on_click(self, e):
        ln = int(self.txt.index(f"@{e.x},{e.y}").split(".")[0])
        if ln in self.lines:
            self.chosen = self.lines[ln]
            self.mark()
        return "break"

    def use(self):
        if self.chosen:
            self.on_pick(self.chosen)
        self.destroy()


class App:
    def __init__(self):
        self.cfg0 = load_config()
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME}  —  {APP_STAGE} {APP_VERSION}")
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"860x{min(1000, sh - 80)}")
        self.root.minsize(700, 560)
        self.root.resizable(True, True)

        # Apply custom icon (removes default Tkinter feather)
        apply_icon(self.root)

        self.V = {}
        for key, default in DEFAULTS.items():
            if key == "custom_css":
                continue
            val = self.cfg0.get(key, default)
            if isinstance(default, bool):
                self.V[key] = tk.BooleanVar(value=bool(val))
            elif isinstance(default, int):
                self.V[key] = tk.IntVar(value=int(val))
            elif isinstance(default, float):
                self.V[key] = tk.DoubleVar(value=float(val))
            else:
                self.V[key] = tk.StringVar(value=str(val))
        try:
            installed = sorted({f for f in tkfont.families(self.root) if not f.startswith("@")})
        except Exception:
            installed = []
        cat = [n for n, _, _ in FONT_CATALOG]
        self.installed = set(installed)
        self.font_values = ["Sans-serif", "Serif", "Monospace"] + cat + \
            [f for f in installed if f not in cat]
        self.loaded_props, self.loaded_pages, self.loaded_source = [], [], ""
        self.q      = queue.Queue()
        self.cancel = threading.Event()
        self.build()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self.poll)

    # ---- helpers ----
    def collect(self):
        c = {k: v.get() for k, v in self.V.items()}
        c["custom_css"] = self.css_text.get("1.0", "end").strip()
        c["token"]      = c["token"].strip()
        return c

    def log(self, msg):
        self.q.put(("log", msg))

    def progress(self, i, n):
        self.q.put(("progress", i, n))

    def append_log(self, msg):
        self.log_box.config(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    @staticmethod
    def open_folder(path):
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            pass

    def set_running(self, on):
        self.export_btn.config(state="disabled" if on else "normal")
        self.cancel_btn.config(state="normal" if on else "disabled")

    def need_basic(self, c):
        if not c["token"] or not c["database"].strip():
            messagebox.showerror("Missing info", "Enter the Notion token and a database / page ID or URL.")
            return False
        return True

    def row(self, parent, r, label, widget, pady=4):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="ne", padx=8, pady=pady)
        widget.grid(row=r, column=1, sticky="we", padx=8, pady=pady)
        parent.columnconfigure(1, weight=1)

    def tab(self, title):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text=title)
        return f

    def combo(self, parent, key, values, state="readonly", width=None):
        kw = {"width": width} if width else {}
        cb = ttk.Combobox(parent, textvariable=self.V[key], values=values, state=state, **kw)
        cb._narrow = bool(width)
        return cb

    def check(self, parent, key, text):
        return ttk.Checkbutton(parent, text=text, variable=self.V[key])

    def section(self, parent, row, text):
        """Small section header label."""
        ttk.Separator(parent, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="we", padx=8, pady=(10, 2))
        ttk.Label(parent, text=text, font=("", 9, "bold"), foreground="#555").grid(
            row=row + 1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 2))

    # ---- actions ----
    def poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "log":
                    self.append_log(item[1])
                elif kind == "progress":
                    _, i, n = item
                    self.bar.config(maximum=max(n, 1), value=i)
                    self.status.set(f"{i} / {n}")
                elif kind == "done":
                    out = item[1]
                    count = item[2]
                    failed = item[3]
                    last_tex = item[4] if len(item) > 4 else ""
                    self.set_running(False)
                    text = f"Exported {count} page(s).\n\n{out}"
                    if last_tex:
                        self.last_latex_text = last_tex
                        self.copy_latex_btn.config(state="normal")
                        text += "\n\nLaTeX export ready! Click '📋 Copy LaTeX' to copy."
                    if failed:
                        text += f"\n\n{len(failed)} problem(s):\n" + "\n".join(
                            f"- {f}: {r}" for f, r in failed[:10])
                    messagebox.showinfo("Done", text)
                    self.open_folder(out)
                elif kind == "cancelled":
                    self.set_running(False)
                    self.append_log("Cancelled. Files exported so far were kept.")
                elif kind == "error":
                    self.set_running(False)
                    messagebox.showerror("Export failed", item[1])
                elif kind == "call":
                    _, fn, res, err = item
                    self.root.config(cursor="")
                    fn(res, err)
                elif kind == "loginend":
                    self.login_btn.config(state="normal")
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def save_gemini_key(self):
        c = self.collect()
        save_config(c)
        messagebox.showinfo("Key Saved", f"Gemini API key saved to local user config:\n{CONFIG_FILE}")

    def copy_latex(self):
        if not getattr(self, "last_latex_text", None):
            messagebox.showinfo("Copy LaTeX", "No LaTeX export is available yet. Run an export with 'LaTeX (.tex)' selected.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.last_latex_text)
        messagebox.showinfo("Copied to Clipboard", "Complete LaTeX document copied to clipboard!")

    def start_export(self):
        try:
            c = self.collect()
        except Exception:
            messagebox.showerror("Invalid value", "Check the numeric fields.")
            return
        if not self.need_basic(c):
            return
        if not c["save_dir"].strip():
            messagebox.showerror("Missing folder", "Choose an output folder on the Output tab.")
            return
        if c.get("gemini_math_ocr"):
            if not _GENAI_AVAILABLE:
                messagebox.showerror(
                    "Package Missing",
                    "The 'google-genai' library is required for Gemini Math OCR.\n\n"
                    "Please install it with:\n  pip install google-genai"
                )
                return
            if not c.get("gemini_api_key", "").strip():
                messagebox.showerror(
                    "Gemini API Key Required",
                    "Math OCR with Gemini Vision is enabled, but no Gemini API Key was entered.\n\n"
                    "Please enter your personal Gemini API key in the 'LaTeX & OCR' tab.\n"
                    "You can get a free key at:\nhttps://aistudio.google.com/"
                )
                return
        save_config(c)
        shown    = self.props_list.selected_labels()
        selected = None
        if self.loaded_pages and self.loaded_source == c["database"].strip():
            sel = self.pages_list.selected_indices()
            if not sel:
                messagebox.showerror("No pages ticked", "Tick at least one page in tab 2, "
                                     "or clear the list by loading pages again.")
                return
            selected = [self.loaded_pages[i] for i in sel]
        self.cancel.clear()
        self.set_running(True)
        self.bar.config(value=0)

        def worker():
            try:
                ex       = Exporter(c, self.loaded_props, shown, self.log, self.progress, self.cancel)
                out, count, failed = ex.run(selected)
                self.q.put(("done", out, count, failed, getattr(ex, "last_tex", "")))
            except Cancelled:
                self.q.put(("cancelled",))
            except Exception as e:
                self.q.put(("error", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def cancel_export(self):
        self.cancel.set()
        self.append_log("Cancelling after the current page...")

    def do_login(self):
        self.login_btn.config(state="disabled")

        def worker():
            try:
                login_to_notion(self.log)
            except Exception as e:
                self.log("Login window error: " + str(e))
            self.q.put(("loginend",))

        threading.Thread(target=worker, daemon=True).start()

    def bg(self, work, done):
        """Run `work` in a thread (UI stays responsive); `done(result, error)` runs in the UI thread."""
        self.root.config(cursor="watch")

        def runner():
            try:
                res, err = work(), None
            except Exception as e:
                res, err = None, e
            self.q.put(("call", done, res, err))

        threading.Thread(target=runner, daemon=True).start()

    def load_props(self):
        c = self.collect()
        if not self.need_basic(c):
            return

        def work():
            return load_property_names(Client(auth=c["token"]), c["database"], c["source_type"])

        def done(names, err):
            if err:
                messagebox.showerror("Could not load properties", str(err))
                return
            self.loaded_props = names
            self.props_list.set_items(names)
            self.sort_combo.config(values=SORT_BUILTIN + names)
            self.filter_combo.config(values=[""] + names + ["Title", "Date"])
            self.hint.set("Placeholders: {title} {date} {index} {created} {edited} {parent}\n"
                          "Your properties: " + " ".join("{%s}" % n for n in names) +
                          "\nFormats: {date:%d-%m-%Y}   {title:40} (truncate)")
            self.append_log(f"Loaded {len(names)} properties.")

        self.bg(work, done)

    def load_pages(self):
        c = self.collect()
        if not self.need_basic(c):
            return

        def done(pages, err):
            if err:
                messagebox.showerror("Could not load pages", str(err))
                return
            self.loaded_pages, self.loaded_source = pages, c["database"].strip()
            labels = []
            for p in pages:
                f = page_fields(p)
                labels.append(f"{f['date'] or '—'}   {f['title']}")
            self.pages_list.set_items(labels)
            self.append_log(f"Loaded {len(pages)} pages. Deselect the ones you don't want.")

        self.bg(lambda: Exporter(c).fetch_roots(), done)

    def preview_names(self):
        try:
            c = self.collect()
        except Exception:
            messagebox.showerror("Invalid value", "Check the numeric fields.")
            return
        if not self.need_basic(c):
            return

        def work():
            return Exporter(c).fetch_roots()[:8]

        def done(pages, err):
            if err:
                messagebox.showerror("Preview failed", str(err))
                return
            names = [build_name(c["name_format"], page_fields(p, i, 2)) for i, p in enumerate(pages, 1)]
            img   = [build_name(c["img_format"], dict(page_fields(p, i, 2), page=n, n="01",
                                                      caption="caption", original="image"))
                     for i, (p, n) in enumerate(zip(pages, names), 1)][:3]
            messagebox.showinfo("Name preview", "Files:\n" + "\n".join(names) +
                                "\n\nImages:\n" + "\n".join(x + ".png" for x in img))

        self.bg(work, done)

    def choose_folder(self):
        d = filedialog.askdirectory(title="Choose output folder")
        if d:
            self.V["save_dir"].set(d)

    def choose_icon_file(self):
        p = filedialog.askopenfilename(
            title="Choose custom icon image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.webp *.svg"),
                       ("All files", "*.*")])
        if p:
            self.V["icon_custom_file"].set(p)

    def select_pages(self, all_):
        self.pages_list.select_all(all_)

    def on_close(self):
        try:
            save_config(self.collect())
        except Exception:
            pass
        self.root.destroy()

    # ---- layout helpers ----
    def page(self, title):
        sf = ScrollFrame(self.nb)
        self.nb.add(sf, text=title)
        return sf.inner

    def group(self, parent, title):
        g = ttk.LabelFrame(parent, text=" " + title + " ", padding=(12, 8))
        g.pack(fill="x", padx=12, pady=(8, 2))
        g.columnconfigure(1, weight=1)
        g._r = 0
        return g

    def field(self, g, label, widget, hint=None):
        r = g._r
        ttk.Label(g, text=label).grid(row=r, column=0, sticky="ne", padx=(0, 12), pady=4)
        narrow = isinstance(widget, (ttk.Button, ttk.Spinbox)) or getattr(widget, "_narrow", False)
        widget.grid(row=r, column=1, sticky="w" if narrow else "we", pady=4)
        r += 1
        if hint:
            ttk.Label(g, text=hint, style="Hint.TLabel", wraplength=540, justify="left").grid(
                row=r, column=1, sticky="w", pady=(0, 4))
            r += 1
        g._r = r

    def tick(self, g, key, text, hint=None):
        ttk.Checkbutton(g, text=text, variable=self.V[key]).grid(
            row=g._r, column=0, columnspan=2, sticky="w", pady=2)
        g._r += 1
        if hint:
            ttk.Label(g, text=hint, style="Hint.TLabel", wraplength=540, justify="left").grid(
                row=g._r, column=0, columnspan=2, sticky="w", padx=(24, 0), pady=(0, 4))
            g._r += 1

    def note(self, g, text, var=None):
        lab = ttk.Label(g, text=text, textvariable=var, style="Hint.TLabel", wraplength=560, justify="left")
        lab.grid(row=g._r, column=0, columnspan=2, sticky="w", pady=(0, 4))
        g._r += 1
        return lab

    def spin(self, parent, key, lo, hi, inc=1, w=8):
        return ttk.Spinbox(parent, from_=lo, to=hi, increment=inc, textvariable=self.V[key], width=w)

    def _on_wheel(self, e):
        """One global mouse-wheel handler: scrolls the list under the cursor, else the page."""
        w = e.widget
        if isinstance(w, str):
            return None
        try:
            if w.winfo_toplevel() is not self.root or w.winfo_class() == "Text":
                return None
        except Exception:
            return None
        num = getattr(e, "num", 0)
        if num == 4:
            steps = -1
        elif num == 5:
            steps = 1
        else:
            d = getattr(e, "delta", 0)
            steps = (-d if sys.platform == "darwin" else -int(d / 120)) or (-1 if d > 0 else 1)
        while w is not None:
            cv = getattr(w, "_wheel_canvas", None)
            if cv is not None:
                lo, hi = cv.yview()
                if (steps < 0 and lo > 0.0) or (steps > 0 and hi < 1.0):
                    cv.yview_scroll(steps * 3, "units")
                    return "break"
            w = getattr(w, "master", None)
        return None

    def _wheel_block(self, e):
        self._on_wheel(e)
        return "break"          # comboboxes / spinboxes must not change value while scrolling

    def font_field(self, g, label, key, allow_same=False, hint=None):
        fr = ttk.Frame(g)
        ent = ttk.Entry(fr, textvariable=self.V[key])
        ent.pack(side="left", fill="x", expand=True)

        def refresh(*_):
            name = self.V[key].get()
            fam = _GENERIC_FONT_ALIAS.get(name, name)
            try:
                ent.config(font=(fam, 12) if fam in self.installed or fam in _GENERIC_FONT_ALIAS.values()
                           else "TkDefaultFont")
            except Exception:
                pass

        def choose():
            FontPicker(self, self.V[key].get(), allow_same, lambda n: self.V[key].set(n))

        ttk.Button(fr, text="Choose font…", command=choose).pack(side="left", padx=(6, 0))
        self.V[key].trace_add("write", refresh)
        refresh()
        self.field(g, label, fr, hint)

    def show_about(self):
        messagebox.showinfo(
            f"About {APP_NAME}",
            f"{APP_NAME}\nVersion {APP_VERSION}  ({APP_STAGE})\n\n"
            "This is a BETA release: all main features work, but it is still new and being tested.\n"
            "Bugs are expected. Please keep a copy of important data, and report problems "
            "together with the text from the log box at the bottom of the window.")

    def apply_preset(self, *_):
        preset = STYLE_PRESETS.get(self.V["theme_preset"].get())
        if preset:
            for k, v in preset.items():
                self.V[k].set(v)

    def pick_color(self):
        cur = self.V["accent_color"].get()
        rgb, hexv = colorchooser.askcolor(color=cur if _HEX_RE.match(cur or "") else "#37352f",
                                          title="Accent color (headings, links, quote bars)")
        if hexv:
            self.V["accent_color"].set(hexv)

    def update_swatch(self, *_):
        try:
            self.swatch.config(bg=self.V["accent_color"].get())
        except Exception:
            pass

    def update_summary(self, *_):
        try:
            fm = [FORMAT_LABELS[k] for k in FORMATS + ["images"] if self.V["fmt_" + k].get()]
            out = self.V["save_dir"].get().strip() or "(choose an output folder in tab 8)"
            self.summary.set("Will export: " + (", ".join(fm) if fm else "nothing selected (tab 3)") +
                             "   →   " + out)
        except Exception:
            pass

    # ---- layout ----
    def build(self):
        V = self.V
        style = ttk.Style()
        try:
            if sys.platform.startswith("win"):
                style.theme_use("vista")
            base = tkfont.nametofont("TkDefaultFont")
            base.configure(size=10, family="Segoe UI" if sys.platform.startswith("win") else base.actual("family"))
            tkfont.nametofont("TkTextFont").configure(size=10)
        except Exception:
            pass
        style.configure("Hint.TLabel", foreground="#6b7280", font=("", 9))
        style.configure("Head.TLabel", font=("", 15, "bold"))
        style.configure("Accent.TButton", font=("", 11, "bold"), padding=(18, 7))
        style.configure("TNotebook.Tab", padding=(11, 6))

        # ---- header ----
        head = ttk.Frame(self.root)
        head.pack(fill="x", padx=14, pady=(10, 0))
        try:
            from PIL import Image, ImageTk
            for ext in (".png", ".ico"):
                ip = resource_path("icon" + ext)
                if ip.exists():
                    self._hdr_icon = ImageTk.PhotoImage(Image.open(str(ip)).convert("RGBA").resize((40, 40), Image.LANCZOS))
                    ttk.Label(head, image=self._hdr_icon).pack(side="left", padx=(0, 10))
                    break
        except Exception:
            pass
        tf = ttk.Frame(head)
        tf.pack(side="left")
        tr = ttk.Frame(tf)
        tr.pack(anchor="w")
        ttk.Label(tr, text=APP_NAME, style="Head.TLabel").pack(side="left")
        tk.Label(tr, text=f" {APP_STAGE} ", bg="#f59e0b", fg="white", font=("", 8, "bold")).pack(
            side="left", padx=8)
        ttk.Label(tf, text="Follow the tabs 1 → 8, then press Export.  Only tabs 1 and 8 are required.",
                  style="Hint.TLabel").pack(anchor="w")

        ttk.Button(head, text="About / Beta", command=self.show_about).pack(side="right")
        self.nb = ttk.Notebook(self.root)
        self.root.bind_all("<MouseWheel>", self._on_wheel)
        self.root.bind_all("<Button-4>", self._on_wheel)
        self.root.bind_all("<Button-5>", self._on_wheel)
        for cls in ("TCombobox", "TSpinbox"):
            self.root.bind_class(cls, "<MouseWheel>", self._wheel_block)
            self.root.bind_class(cls, "<Button-4>", self._wheel_block)
            self.root.bind_class(cls, "<Button-5>", self._wheel_block)

        # ═══════════════ 1 · Source ═══════════════
        t = self.page("1  Source")
        g = self.group(t, "Notion connection")
        self.token_entry = ttk.Entry(g, textvariable=V["token"], show="•")
        self.field(g, "Integration token", self.token_entry,
                   "Create one at notion.so/my-integrations, then in Notion open your page → ••• → "
                   "Connections → add your integration.")
        self.show_token = tk.BooleanVar(value=False)
        o = ttk.Frame(g)
        ttk.Checkbutton(o, text="Show token", variable=self.show_token,
                        command=lambda: self.token_entry.config(show="" if self.show_token.get() else "•")
                        ).pack(side="left")
        ttk.Checkbutton(o, text="Remember on this PC (saved as plain text)",
                        variable=V["remember_token"]).pack(side="left", padx=14)
        ttk.Button(o, text="Open integrations page ↗",
                   command=lambda: webbrowser.open("https://www.notion.so/my-integrations")).pack(side="left")
        self.field(g, "", o)

        g = self.group(t, "What to export")
        self.field(g, "Database / page link", ttk.Entry(g, textvariable=V["database"]),
                   "Paste the Notion link (or ID). To export several, separate links with spaces or commas.")
        self.field(g, "It is a…", self.combo(g, "source_type", SOURCE_TYPES, width=18),
                   "Leave on Auto-detect unless the app guesses wrong.")

        g = self.group(t, "Private pages — Browser PDF engine only")
        self.tick(g, "use_login", "Use my saved Notion login",
                  "Only needed when the PDF engine is set to “Browser”. The default API engine does not need this.")
        self.login_btn = ttk.Button(g, text="Log in to Notion…", command=self.do_login)
        self.field(g, "", self.login_btn, "A browser window opens: sign in, then close the window.")

        # ═══════════════ 2 · Pages ═══════════════
        t = self.page("2  Pages")
        g = self.group(t, "Choose which pages")
        pr = ttk.Frame(g)
        ttk.Button(pr, text="Load pages", command=self.load_pages).pack(side="left")
        ttk.Button(pr, text="Select all", command=lambda: self.select_pages(True)).pack(side="left", padx=6)
        ttk.Button(pr, text="Clear", command=lambda: self.select_pages(False)).pack(side="left")
        self.field(g, "Page list", pr, "Optional. If you never press “Load pages”, every page is exported. "
                                       "After loading, only ticked pages are exported.")
        self.pages_list = CheckList(g, height=210, empty_text="Press “Load pages” to see your pages here.")
        self.field(g, "", self.pages_list)
        self.field(g, "", ttk.Label(g, textvariable=self.pages_list.info, style="Hint.TLabel"))

        g = self.group(t, "Order & filter")
        sr = ttk.Frame(g)
        self.sort_combo = ttk.Combobox(sr, textvariable=V["sort_by"], values=SORT_BUILTIN, width=22)
        self.sort_combo.pack(side="left")
        ttk.Checkbutton(sr, text="Descending", variable=V["sort_desc"]).pack(side="left", padx=10)
        self.field(g, "Sort by", sr)
        fr = ttk.Frame(g)
        self.filter_combo = ttk.Combobox(fr, textvariable=V["filter_prop"], width=16)
        self.filter_combo.pack(side="left")
        ttk.Combobox(fr, textvariable=V["filter_op"], values=["contains", "does not contain", "equals"],
                     state="readonly", width=15).pack(side="left", padx=4)
        ttk.Entry(fr, textvariable=V["filter_value"], width=18).pack(side="left")
        self.field(g, "Only pages where", fr, "Leave empty for no filter.")
        self.field(g, "Max pages", self.spin(g, "max_pages", 0, 100000), "0 = no limit.")

        g = self.group(t, "File names")
        self.field(g, "Name format", ttk.Entry(g, textvariable=V["name_format"]))
        pre = ttk.Combobox(g, values=NAME_PRESETS, state="readonly")
        pre.bind("<<ComboboxSelected>>", lambda e: V["name_format"].set(pre.get()))
        self.field(g, "Examples", pre)
        self.hint = tk.StringVar(value="Placeholders: {title} {date} {index} {created} {edited} {parent}\n"
                                       "Click “Load properties” (tab 4) to list your own.\n"
                                       "Formats: {date:%d-%m-%Y}   {title:40} (truncate)")
        self.note(g, "", self.hint)
        self.field(g, "", ttk.Button(g, text="Preview names", command=self.preview_names))

        # ═══════════════ 3 · Formats ═══════════════
        t = self.page("3  Formats")
        g = self.group(t, "Export as (tick one or more)")
        ff = ttk.Frame(g)
        for n, k in enumerate(FORMATS + ["images"]):
            ttk.Checkbutton(ff, text=FORMAT_LABELS[k], variable=V["fmt_" + k]).grid(
                row=n // 4, column=n % 4, sticky="w", padx=(0, 22), pady=3)
        self.field(g, "Formats", ff)
        g = self.group(t, "PDF engine")
        self.field(g, "Engine", self.combo(g, "engine", ENGINES),
                   "API = fast, no login, uses your Design tab settings (fonts, colors…).\n"
                   "Browser = prints the real Notion page (slower; needs login for private pages; "
                   "ignores Design settings).")
        g = self.group(t, "Sub-pages")
        self.field(g, "Sub-pages", self.combo(g, "sub_mode", SUB_MODES),
                   "Skip, put inside the parent page, or export each as its own file.")
        self.field(g, "Depth", self.spin(g, "sub_depth", 1, 10), "How many levels of sub-pages to follow.")
        self.tick(g, "sub_dbs", "Also export rows of databases inside pages (separate files mode)")
        g = self.group(t, "Combined file")
        self.tick(g, "combine", "Also create one combined HTML / Markdown / LaTeX file")

        # ═══════════════ 4 · Design ═══════════════
        t = self.page("4  Design")
        g = self.group(t, "Quick style")
        pc = ttk.Combobox(g, textvariable=V["theme_preset"], values=list(STYLE_PRESETS), state="readonly")
        pc.bind("<<ComboboxSelected>>", self.apply_preset)
        self.field(g, "Style preset", pc,
                   "Picks fonts, spacing and colors in one click. You can still change every setting below.")

        g = self.group(t, "Fonts")
        self.font_field(g, "Body font", "font_family", False,
                        "Press “Choose font…” to see every font in its own style. Arabic: Cairo, Tajawal, Amiri…")
        self.font_field(g, "Heading font", "heading_font", True)
        self.tick(g, "web_fonts", "Download fonts from Google Fonts when needed (internet required)",
                  "Fonts such as Inter, Lora, Playfair Display or Cairo are not on most PCs. Tick this to use them.")
        self.field(g, "Font size (px)", self.spin(g, "base_font_size", 10, 28))
        self.field(g, "Line spacing", self.spin(g, "line_spacing", 1.0, 3.0, 0.1))
        self.field(g, "Text alignment", self.combo(g, "text_align", TEXT_ALIGNS, width=14))
        self.field(g, "Title alignment", self.combo(g, "heading_align", HEAD_ALIGNS, width=14))

        g = self.group(t, "Color")
        cr = ttk.Frame(g)
        ttk.Entry(cr, textvariable=V["accent_color"], width=10).pack(side="left")
        self.swatch = tk.Label(cr, width=4, relief="solid", borderwidth=1)
        self.swatch.pack(side="left", padx=6)
        ttk.Button(cr, text="Choose…", command=self.pick_color).pack(side="left")
        V["accent_color"].trace_add("write", self.update_swatch)
        self.update_swatch()
        self.field(g, "Accent color", cr, "Used for headings, links, quote bars and the title line.")

        g = self.group(t, "Title area")
        self.tick(g, "title_separator", "Show a colored line under the page title")
        self.field(g, "Page icon", self.combo(g, "icon_mode", ICON_MODES, width=22))
        icon_row = ttk.Frame(g)
        ttk.Entry(icon_row, textvariable=V["icon_custom_file"]).pack(side="left", fill="x", expand=True)
        ttk.Button(icon_row, text="Browse…", command=self.choose_icon_file).pack(side="left", padx=4)
        self.field(g, "Custom icon file", icon_row, "Used only when “Custom icon file” is selected above.")
        self.tick(g, "cover_page", "Cover page: title, icon and properties alone on page 1")

        g = self.group(t, "Properties (database fields)")
        self.field(g, "Layout", self.combo(g, "prop_layout", PROP_LAYOUTS, width=22),
                   "Notion Table · Inline Pills · Minimalist List · Hidden")
        self.field(g, "Date format", self.combo(g, "date_format_props", DATE_PRESETS, state="normal", width=22),
                   "Or type any pattern, e.g. %d.%m.%Y")
        self.field(g, "", ttk.Button(g, text="Load properties", command=self.load_props),
                   "Load the list, then keep selected only the properties you want shown.")
        self.props_list = CheckList(g, height=150, empty_text="Press “Load properties” first (all are shown until then).")
        self.field(g, "Show these", self.props_list, "Untick the properties you do not want in the export.")
        pb = ttk.Frame(g)
        ttk.Button(pb, text="Tick all", command=lambda: self.props_list.select_all(True)).pack(side="left")
        ttk.Button(pb, text="Untick all", command=lambda: self.props_list.select_all(False)).pack(side="left", padx=6)
        ttk.Label(pb, textvariable=self.props_list.info, style="Hint.TLabel").pack(side="left", padx=8)
        self.field(g, "", pb)

        g = self.group(t, "Content")
        self.tick(g, "render_math", "Render math equations nicely (KaTeX, internet required)",
                  "Without internet, equations are shown as plain LaTeX text.")
        self.tick(g, "expand_toggles", "Expand all toggle blocks")
        self.field(g, "Links", self.combo(g, "links", LINK_MODES))
        self.tick(g, "light_theme", "Force light theme  (Browser engine only)")
        self.tick(g, "clean_layout", "Hide Notion sidebar / top bar  (Browser engine only)")
        self.css_text = tk.Text(g, height=5, width=50)
        self.css_text.insert("1.0", self.cfg0.get("custom_css", ""))
        self.field(g, "Custom CSS", self.css_text, "For experts. Example: h1 { color: #c00; }")

        # ═══════════════ 5 · Images ═══════════════
        t = self.page("5  Images")
        g = self.group(t, "Images inside documents")
        self.field(g, "Handling", self.combo(g, "img_handling", IMG_MODES),
                   "Notion image links expire after about an hour, so “Embed” or “Save locally” is safest.")
        self.tick(g, "optimize_images", "Shrink big photos for PDF / Word (faster export, smaller files)")
        self.field(g, "Max image size (px)", self.spin(g, "image_max_px", 600, 4000, 100, 8),
                   "Saved image files are never changed — only the copy inside the PDF / Word file.")
        g = self.group(t, "Image layout (PDF / HTML / Word)")
        self.tick(g, "maximize_images", "Maximize images (full page width)")
        self.tick(g, "one_image_per_page", "One image per page")
        self.tick(g, "show_image_names", "Show image file names under images (when Notion has no caption)")
        cf = ttk.Frame(g)
        ttk.Combobox(cf, textvariable=V["caption_format"], values=CAPTION_FMTS, width=28).pack(side="left")
        self.field(g, "Caption format", cf, "Placeholders: {name} {ext} {n} {original} {caption}")
        g = self.group(t, "Saving image files  (tick “Images” in tab 3)")
        self.field(g, "File name format", ttk.Entry(g, textvariable=V["img_format"]),
                   "Placeholders: {page} {title} {n} {caption} {original} {date} {index} {parent}")
        ip = ttk.Combobox(g, values=IMG_PRESETS, state="readonly")
        ip.bind("<<ComboboxSelected>>", lambda e: V["img_format"].set(ip.get()))
        self.field(g, "Examples", ip)
        self.tick(g, "img_subfolder", "Put each page's images in its own folder")
        self.tick(g, "img_cover", "Include page cover images ({n} = cover)")

        # ═══════════════ 6 · PDF ═══════════════
        t = self.page("6  PDF")
        g = self.group(t, "Page")
        self.field(g, "Page size", self.combo(g, "page_size", PAGE_SIZES, width=14))
        self.field(g, "Orientation", self.combo(g, "orientation", ["Portrait", "Landscape"], width=14))
        self.field(g, "Margin (mm)", self.spin(g, "margin_mm", 0, 50),
                   "20 mm is comfortable for A4. Use 10 for denser pages.")
        self.field(g, "Scale (%)", self.spin(g, "scale", 10, 200))
        self.tick(g, "print_background", "Print background colors")
        self.tick(g, "remove_blank_pages", "Automatically remove empty pages",
                  "Deletes pages that contain no text, image or drawing (for example after a page break).")
        g = self.group(t, "Page numbers")
        self.tick(g, "page_numbers", "Add page numbers")
        self.field(g, "Position", self.combo(g, "page_num_position", PAGENUM_POS, width=18))
        self.field(g, "Format", self.combo(g, "page_num_format", PAGENUM_FMT, width=18))

        # ═══════════════ 7 · LaTeX & AI ═══════════════
        t = self.page("7  LaTeX & AI")
        g = self.group(t, "LaTeX (.tex)")
        self.tick(g, "fmt_tex", "Export as LaTeX (.tex) document",
                  "Images are written as comments in the .tex for now. Compile with pdflatex "
                  "(xelatex for Arabic).")
        cb = ttk.Frame(g)
        ttk.Button(cb, text="📋 Copy last exported LaTeX", command=self.copy_latex).pack(side="left")
        self.field(g, "Clipboard", cb)
        g = self.group(t, "Gemini Math OCR — whiteboard photos → LaTeX")
        self.note(g, "Each user enters their own key. It is stored only in your local "
                     "~/.notion_pdf_exporter/config.json.")
        kf = ttk.Frame(g)
        self.gemini_key_entry = ttk.Entry(kf, textvariable=V["gemini_api_key"], show="•")
        self.gemini_key_entry.pack(side="left", fill="x", expand=True)
        self.show_gemini_key = tk.BooleanVar(value=False)
        ttk.Checkbutton(kf, text="Show", variable=self.show_gemini_key,
                        command=lambda: self.gemini_key_entry.config(
                            show="" if self.show_gemini_key.get() else "•")).pack(side="left", padx=6)
        ttk.Button(kf, text="Save", command=self.save_gemini_key).pack(side="left")
        ttk.Button(kf, text="Get free key ↗",
                   command=lambda: webbrowser.open("https://aistudio.google.com/")).pack(side="left", padx=6)
        self.field(g, "Gemini API key", kf)
        self.tick(g, "gemini_math_ocr", "Scan images with Gemini Math OCR")
        self.field(g, "Model", self.combo(g, "gemini_model", GEMINI_MODELS, state="normal"),
                   "You can type any Gemini model name here.")
        self.tick(g, "keep_whiteboard_image", "Keep a note of the original image below the transcription")

        # ═══════════════ 8 · Output ═══════════════
        t = self.page("8  Output")
        g = self.group(t, "Where to save")
        orow = ttk.Frame(g)
        ttk.Entry(orow, textvariable=V["save_dir"]).pack(side="left", fill="x", expand=True)
        ttk.Button(orow, text="Browse…", command=self.choose_folder).pack(side="left", padx=4)
        self.field(g, "Output folder  (required)", orow)
        g = self.group(t, "PDF files")
        self.field(g, "PDF output", self.combo(g, "output_mode", OUTPUT_MODES))
        self.field(g, "Merged file name", ttk.Entry(g, textvariable=V["merged_name"]))
        self.tick(g, "bookmarks", "Add bookmarks to the merged PDF")
        g = self.group(t, "Speed & reliability")
        self.field(g, "Parallel downloads", self.spin(g, "workers", 1, 8),
                   "Pages and images are fetched in the background while the previous page is rendered. "
                   "Notion limits requests (~3 per second), so more than 4 rarely helps.")
        self.tick(g, "skip_existing", "Skip files already exported (resume an interrupted export)")
        self.field(g, "Retries on failure", self.spin(g, "retries", 0, 5))
        self.field(g, "Extra wait per page (s)", self.spin(g, "extra_wait", 0, 60, 0.5),
                   "Browser engine only.")

        # ---- bottom bar ----
        run = ttk.Frame(self.root)
        self.export_btn = ttk.Button(run, text="▶  Export", style="Accent.TButton", command=self.start_export)
        self.export_btn.pack(side="left")
        self.cancel_btn = ttk.Button(run, text="Cancel", command=self.cancel_export, state="disabled")
        self.cancel_btn.pack(side="left", padx=8)
        self.copy_latex_btn = ttk.Button(run, text="📋 Copy LaTeX", command=self.copy_latex, state="disabled")
        self.copy_latex_btn.pack(side="left")
        self.status = tk.StringVar()
        ttk.Label(run, textvariable=self.status).pack(side="right")
        self.summary = tk.StringVar()
        sumlab = ttk.Label(self.root, textvariable=self.summary, style="Hint.TLabel")
        self.bar = ttk.Progressbar(self.root, mode="determinate")
        logf = ttk.Frame(self.root)
        self.log_box = tk.Text(logf, height=10, state="disabled", bg="#f7f7f7", relief="flat",
                               borderwidth=1, font=("Consolas" if sys.platform.startswith("win") else "Courier", 9),
                               wrap="word")
        lsb = ttk.Scrollbar(logf, command=self.log_box.yview)
        self.log_box.config(yscrollcommand=lsb.set)
        self.log_box.pack(side="left", fill="both", expand=True)
        lsb.pack(side="right", fill="y")
        logf.pack(side="bottom", fill="x", padx=12, pady=(2, 8))
        self.bar.pack(side="bottom", fill="x", padx=12, pady=2)
        run.pack(side="bottom", fill="x", padx=12, pady=4)
        sumlab.pack(side="bottom", fill="x", padx=14)
        self.nb.pack(side="top", fill="both", expand=True, padx=10, pady=(8, 4))
        for k in FORMATS + ["images"]:
            V["fmt_" + k].trace_add("write", self.update_summary)
        V["save_dir"].trace_add("write", self.update_summary)
        self.update_summary()

    def run(self):
        self.root.mainloop()


def main():
    if tk is None:
        raise SystemExit("Tkinter is not available in this Python installation.")
    _windows_integration()
    App().run()


if __name__ == "__main__":
    main()
