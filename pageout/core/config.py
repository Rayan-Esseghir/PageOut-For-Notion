"""Settings, constants, defaults and config load/save."""

import json
import os

APP_NAME = "PageOut for Notion"


APP_VERSION = "1.0.0-rc.1"


APP_STAGE = "RC"


CONFIG_VERSION = 5


CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".notion_pdf_exporter")


CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


PROFILE_DIR = os.path.join(CONFIG_DIR, "browser_profile")  # saved Notion login


LINK_MODES = ["Keep all links", "Remove all links", "Remove only Notion-internal links"]


OUTPUT_MODES = ["Merged + individual files", "Merged file only", "Individual files only"]


PAGE_SIZES = ["A3", "A4", "A5", "Letter", "Legal", "Tabloid"]


SORT_BUILTIN = ["Date", "Title", "Created", "Last edited", "Database order"]


SOURCE_TYPES = ["Auto-detect", "Database", "Single page"]


ENGINES = ["API (fast, no login needed)", "Browser (exact Notion look)"]


SUB_MODES = ["Skip", "Inline in parent", "Separate files"]


IMG_MODES = ["Embed in file", "Save locally & link", "Keep Notion link"]


ICON_MODES = ["Show page icon", "Hide icon", "Custom icon file"]


PROP_LAYOUTS = ["Notion Table", "Inline Pills", "Minimalist List", "Hidden"]


FONT_FAMILIES = ["Sans-serif", "Serif", "Monospace"]


TEXT_ALIGNS = ["Left", "Justify"]


HEAD_ALIGNS = ["Left", "Center"]


DATE_PRESETS = [
    "YYYY-MM-DD",
    "DD/MM/YYYY",
    "MM/DD/YYYY",
    "MMM DD, YYYY",
    "MMMM D, YYYY",
    "D MMM YYYY",
    "ISO 8601",
    "Relative",
]


PAGENUM_POS = ["Bottom Center", "Bottom Right", "Top Right"]


PAGENUM_FMT = ["Page X of Y", "X"]


CAPTION_FMTS = ["{name}", "{name}.{ext}", "Figure {n}: {name}", "{original}", "{caption}"]


NAME_PRESETS = ["{date} - {title}", "{title}", "{index} - {title}", "{date:%Y-%m-%d} {title:60}", "{created} - {title}"]


IMG_PRESETS = ["{page}_{n}", "{title} - {n}", "{date} - {title} - {n}", "{page}_{n} - {caption}", "{original}"]


MD_PRESETS = ["GFM", "Vanilla", "Obsidian"]
MATH_ENGINES = ["Bundled (offline)", "CDN (internet)", "None"]
LATEX_IMG_MODES = ["Include images", "Comments only"]
DB_EXPORT_MODES = ["None", "Index page", "Table of properties", "CSV file", "Group by"]

# Phase 16: Sync targets for post-export
SYNC_TARGETS = ["None", "Local folder", "Google Drive", "Dropbox", "S3", "Git repo"]


# (name, category, is_google_font)   category: sans | serif | mono | arabic
FONT_CATALOG = [
    ("Segoe UI", "sans", False),
    ("Arial", "sans", False),
    ("Calibri", "sans", False),
    ("Verdana", "sans", False),
    ("Tahoma", "sans", False),
    ("Trebuchet MS", "sans", False),
    ("Century Gothic", "sans", False),
    ("Inter", "sans", True),
    ("Roboto", "sans", True),
    ("Open Sans", "sans", True),
    ("Lato", "sans", True),
    ("Poppins", "sans", True),
    ("Nunito", "sans", True),
    ("Montserrat", "sans", True),
    ("Source Sans 3", "sans", True),
    ("IBM Plex Sans", "sans", True),
    ("Georgia", "serif", False),
    ("Times New Roman", "serif", False),
    ("Cambria", "serif", False),
    ("Palatino Linotype", "serif", False),
    ("Garamond", "serif", False),
    ("Book Antiqua", "serif", False),
    ("Merriweather", "serif", True),
    ("Lora", "serif", True),
    ("Playfair Display", "serif", True),
    ("Source Serif 4", "serif", True),
    ("Crimson Pro", "serif", True),
    ("EB Garamond", "serif", True),
    ("Libre Baskerville", "serif", True),
    ("Consolas", "mono", False),
    ("Cascadia Code", "mono", False),
    ("Courier New", "mono", False),
    ("Fira Code", "mono", True),
    ("JetBrains Mono", "mono", True),
    ("Source Code Pro", "mono", True),
    ("IBM Plex Mono", "mono", True),
    ("Cairo", "arabic", True),
    ("Tajawal", "arabic", True),
    ("Amiri", "arabic", True),
    ("Noto Naskh Arabic", "arabic", True),
    ("Noto Sans Arabic", "arabic", True),
    ("IBM Plex Sans Arabic", "arabic", True),
    ("Almarai", "arabic", True),
    ("Scheherazade New", "arabic", True),
]


FONT_CATEGORY = {n: c for n, c, _ in FONT_CATALOG}


GOOGLE_FONTS = {n for n, _, g in FONT_CATALOG if g}


SAME_AS_BODY = "Same as body"


STYLE_PRESETS = {
    "Notion Classic": dict(
        font_family="Sans-serif",
        heading_font=SAME_AS_BODY,
        base_font_size=16,
        line_spacing=1.5,
        text_align="Left",
        heading_align="Left",
        title_separator=False,
        accent_color="#37352f",
        web_fonts=False,
    ),
    "Modern Blue": dict(
        font_family="Inter",
        heading_font=SAME_AS_BODY,
        base_font_size=16,
        line_spacing=1.65,
        text_align="Left",
        heading_align="Left",
        title_separator=True,
        accent_color="#2563eb",
        web_fonts=True,
    ),
    "Academic Serif": dict(
        font_family="Cambria",
        heading_font=SAME_AS_BODY,
        base_font_size=15,
        line_spacing=1.7,
        text_align="Justify",
        heading_align="Left",
        title_separator=True,
        accent_color="#1f2937",
        web_fonts=False,
    ),
    "Elegant": dict(
        font_family="Lora",
        heading_font="Playfair Display",
        base_font_size=16,
        line_spacing=1.7,
        text_align="Left",
        heading_align="Left",
        title_separator=True,
        accent_color="#9a3412",
        web_fonts=True,
    ),
    "Clean Report": dict(
        font_family="Calibri",
        heading_font=SAME_AS_BODY,
        base_font_size=15,
        line_spacing=1.55,
        text_align="Left",
        heading_align="Center",
        title_separator=True,
        accent_color="#0f766e",
        web_fonts=False,
    ),
    "Developer Mono": dict(
        font_family="Consolas",
        heading_font=SAME_AS_BODY,
        base_font_size=14,
        line_spacing=1.6,
        text_align="Left",
        heading_align="Left",
        title_separator=False,
        accent_color="#374151",
        web_fonts=False,
    ),
    "Arabic (Cairo)": dict(
        font_family="Cairo",
        heading_font=SAME_AS_BODY,
        base_font_size=16,
        line_spacing=1.85,
        text_align="Left",
        heading_align="Left",
        title_separator=True,
        accent_color="#0f766e",
        web_fonts=True,
    ),
}


FORMATS = ["pdf", "html", "md", "txt", "docx", "json", "tex", "epub", "rst", "adoc"]


FORMAT_LABELS = {
    "pdf": "PDF",
    "html": "HTML",
    "md": "Markdown",
    "txt": "Text",
    "docx": "Word",
    "json": "JSON",
    "tex": "LaTeX (.tex)",
    "epub": "EPUB",
    "rst": "reStructuredText",
    "adoc": "AsciiDoc",
    "images": "Images",
}


FOLDERS = {
    "pdf": "PDF",
    "html": "HTML",
    "md": "Markdown",
    "txt": "Text",
    "docx": "Word",
    "json": "JSON",
    "tex": "LaTeX",
    "epub": "EPUB",
    "rst": "reStructuredText",
    "adoc": "AsciiDoc",
}


EXTS = {"pdf": ".pdf", "html": ".html", "md": ".md", "txt": ".txt", "docx": ".docx", "json": ".json", "tex": ".tex", "epub": ".epub", "rst": ".rst", "adoc": ".adoc"}


# Front matter presets for Hugo/Jekyll static site generators
FM_PRESETS = ["None", "Hugo", "Jekyll"]


GEMINI_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
]


DEFAULTS = {
    # source
    "token": "",
    "remember_token": False,
    "database": "",
    "workspace": "",
    "source_type": SOURCE_TYPES[0],
    "sources": [],
    "use_login": True,
    # pages
    "name_format": "{date} - {title}",
    "sort_by": "Date",
    "sort_desc": False,
    "filter_prop": "",
    "filter_op": "contains",
    "filter_value": "",
    "max_pages": 0,
    "group_by": "",
    # formats
    "fmt_pdf": True,
    "fmt_html": False,
    "fmt_md": False,
    "fmt_txt": False,
    "fmt_docx": False,
    "fmt_json": False,
    "fmt_tex": False,
    "fmt_images": False,
    "engine": ENGINES[0],
    "sub_mode": SUB_MODES[0],
    "sub_depth": 3,
    "sub_dbs": False,
    "combine": False,
    # Gemini Math OCR
    "gemini_api_key": "",
    "gemini_math_ocr": False,
    "gemini_model": "gemini-3.5-flash-lite",
    "keep_whiteboard_image": False,
    # images
    "img_handling": IMG_MODES[0],
    "img_format": "{page}_{n}",
    "img_subfolder": True,
    "img_cover": False,
    # image layout (new)
    "maximize_images": False,
    "one_image_per_page": False,
    "show_image_names": False,
    "caption_format": "{name}",
    # content
    "expand_toggles": True,
    "light_theme": True,
    "clean_layout": True,
    "links": LINK_MODES[0],
    "custom_css": "",
    # pdf
    "page_size": "A4",
    "orientation": "Portrait",
    "margin_mm": 20,
    "scale": 100,
    "print_background": True,
    "page_numbers": False,
    "page_num_position": PAGENUM_POS[0],
    "page_num_format": PAGENUM_FMT[0],
    # output
    "save_dir": "",
    "output_mode": OUTPUT_MODES[0],
    "merged_name": "All_Pages",
    "bookmarks": True,
    "skip_existing": False,
    "extra_wait": 2.0,
    "retries": 1,
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
    # Phase 15: More formats (EPUB, RST, AsciiDoc)
    "fmt_epub": False,
    "fmt_rst": False,
    "fmt_adoc": False,
    "md_front_matter_preset": FM_PRESETS[0],
    "epub_language": "en",
    "epub_author": "PageOut for Notion",
    "epub_description": "",
    "epub_publisher": "PageOut for Notion",
    # Phase 13: Better PDF
    "table_of_contents": False,
    "running_header": False,
    "header_format": "{title}",
    "watermark_text": "",
    "watermark_opacity": 0.15,
    "booklet_mode": False,
    "cover_page_improved": True,
    # v5.1: design / speed
    "theme_preset": "Notion Classic",
    "heading_font": SAME_AS_BODY,
    "accent_color": "#37352f",
    "web_fonts": False,
    "render_math": True,
    "workers": 4,
    "optimize_images": True,
    "image_max_px": 1600,
    # v1.0: sync, links, math, formats
    "incremental": True,
    "force": False,
    "rewrite_links": True,
    "math_engine": MATH_ENGINES[0],
    "latex_images": LATEX_IMG_MODES[0],
    "md_preset": MD_PRESETS[0],
    "db_export": DB_EXPORT_MODES[0],
    "allow_plaintext_secrets": False,
    # P4: Fast markdown via API with fallback
    "fast_markdown": True,
    # profiling (P1)
    "profile_timing": False,
    # U2: Look & Navigation
    "theme": "light",  # light, dark, system
    "ui_mode": "advanced",  # simple, advanced
    "ui_scale": 1.0,
    "window_geometry": "",  # saved window geometry
    "window_state": "normal",  # normal, zoomed
    "last_page": "1  Source",  # last active tab
    # Phase 9: Settings persistence preferences
    "prefs_auto_save": True,
    "prefs_remember_window": True,
    "prefs_confirm_exit": False,
    "prefs_tooltip_delay": 500,
        "prefs_large_export_threshold_mb": 500,
        "prefs_large_export_estimate_minutes": 0,
        "prefs_enable_long_paths": True,
        "prefs_high_contrast": False,
        "prefs_ui_rtl": False,
        "prefs_auto_save_interval": 300,
    # Phase 8: Font preferences
    "font_favorites": '["Inter", "Roboto", "Segoe UI", "Arial", "Source Sans 3"]',
    "font_recent": "[]",
    # U6: Onboarding & help
    "first_run_complete": False,
    "has_seen_onboarding": False,
    # Phase 16: Sync configuration
    "sync_target": "None",
    "sync_path": "",
    "sync_branch": "main",
    "gdrive_folder_id": "",
    "dropbox_path": "/exports",
    "s3_bucket": "",
    "s3_prefix": "exports",
    "sync_after_export": False,
}


def load_config():
    from pageout.core import secrets

    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    old_ver = int(cfg.get("_ver", 0))
    if old_ver < 2:  # new, more comfortable defaults
        cfg["margin_mm"] = DEFAULTS["margin_mm"]
        cfg["line_spacing"] = DEFAULTS["line_spacing"]
    if old_ver < CONFIG_VERSION:  # Phase 9: Add settings persistence preferences with defaults
        cfg.setdefault("prefs_auto_save", DEFAULTS["prefs_auto_save"])
        cfg.setdefault("prefs_remember_window", DEFAULTS["prefs_remember_window"])
        cfg.setdefault("prefs_confirm_exit", DEFAULTS["prefs_confirm_exit"])
        cfg.setdefault("prefs_tooltip_delay", DEFAULTS["prefs_tooltip_delay"])
    if old_ver < 5:  # Phase 13: Add Better PDF settings
        cfg.setdefault("table_of_contents", DEFAULTS["table_of_contents"])
        cfg.setdefault("running_header", DEFAULTS["running_header"])
        cfg.setdefault("header_format", DEFAULTS["header_format"])
        cfg.setdefault("watermark_text", DEFAULTS["watermark_text"])
        cfg.setdefault("watermark_opacity", DEFAULTS["watermark_opacity"])
        cfg.setdefault("booklet_mode", DEFAULTS["booklet_mode"])
        cfg.setdefault("cover_page_improved", DEFAULTS["cover_page_improved"])
    cfg["_ver"] = CONFIG_VERSION
    migrated = False
    for key, name in secrets.SECRET_KEYS.items():
        file_value = cfg.get(key) or ""
        if file_value and old_ver < 3 and secrets.keyring_available() and secrets.set_secret(name, file_value):
            migrated = True  # v<3 stored plain text: move into the keyring
        if not cfg.get(key):
            cfg[key] = secrets.get_secret(name)
    if migrated:
        _write_config(cfg, strip_secrets=True)
    if not cfg.get("token"):
        cfg["token"] = os.environ.get("NOTION_TOKEN", "")
    if not cfg.get("gemini_api_key"):
        cfg["gemini_api_key"] = os.environ.get("GEMINI_API_KEY", "")
    return cfg


def _write_config(data, strip_secrets):
    data = dict(data)
    data["_ver"] = CONFIG_VERSION
    if strip_secrets:
        for key in ("token", "gemini_api_key"):
            data[key] = ""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def save_config(cfg):
    """Save settings. Secrets go to the OS keyring; plain text only if the user opted in.
    Returns a warning string (empty when everything was stored as requested)."""
    from pageout.core import secrets

    data = dict(cfg)
    warning = ""
    for key, name in secrets.SECRET_KEYS.items():
        value = data.get(key) or ""
        keep = bool(data.get("remember_token")) if key == "token" else bool(value)
        if not (keep and value):
            secrets.set_secret(name, "")  # forget anything stored earlier
            data[key] = ""
        elif secrets.set_secret(name, value):
            data[key] = ""  # safely in the keyring, not in the file
        elif not data.get("allow_plaintext_secrets"):
            data[key] = ""
            warning = (
                "No OS keyring available: the token / API key was NOT saved. "
                "Install the 'keyring' package or tick 'Allow plain-text storage'."
            )
    _write_config(data, strip_secrets=False)
    return warning
