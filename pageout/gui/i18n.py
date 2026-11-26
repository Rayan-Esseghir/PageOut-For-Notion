"""Internationalization and localization for the GUI.

This module provides string translation support for the PageOut GUI.
Strings are stored as simple Python dicts keyed by language code.
"""

from typing import Dict, Optional

# English strings - all UI text goes here
EN = {
    # Main window
    "title_prefix": "PageOut",
    "status_bar": "Follow the tabs 1 → 8, then press Export. Only tabs 1 and 8 are required.",

    # Tabs
    "tab_source": "1  Source",
    "tab_pages": "2  Pages",
    "tab_formats": "3  Formats",
    "tab_design": "4  Design",
    "tab_images": "5  Images",
    "tab_pdf": "6  PDF",
    "tab_latex": "7  LaTeX & AI",
    "tab_output": "8  Output",

    # Source tab - Notion connection
    "integration_token": "Integration token",
    "show_token": "Show token",
    "remember_token": "Remember on this PC (OS keyring)",
    "open_integrations": "Open integrations page ↗",
    "allow_plaintext": "Allow plain-text storage if no OS keyring is available",
    "notion_connection": "Notion connection",
    "database_page_link": "Database / page link",
    "it_is_a": "It is a…",
    "private_pages": "Private pages — Browser PDF engine only",
    "use_login": "Use my saved Notion login",
    "log_in_to_notion": "Log in to Notion…",
    "login_instructions": "A browser window opens: sign in, then close the window.",

    # Pages tab
    "choose_pages": "Choose which pages",
    "load_pages": "Load pages",
    "select_all": "Select all",
    "clear": "Clear",
    "page_list": "Page list (optional)",
    "page_list_hint": "If never pressed, all pages are exported. After loading, only ticked pages are exported.",
    "order_filter": "Order & filter",
    "sort_by": "Sort by",
    "descending": "Descending",
    "only_pages_where": "Only pages where",
    "max_pages": "Max pages",
    "file_names": "File names",
    "name_format": "Name format",
    "examples": "Examples",
    "preview_names": "Preview names",
    "name_hint": "Placeholders: {title} {date} {index} {created} {edited} {parent}\nClick \"Load properties\" to list your own.\nFormats: {date:%d-%m-%Y}   {title:40} (truncate)",

    # Formats tab
    "export_as": "Export as (tick one or more)",
    "pdf": "PDF",
    "html": "HTML",
    "markdown": "Markdown",
    "text": "Text",
    "word": "Word",
    "json": "JSON",
    "latex": "LaTeX (.tex)",
    "images": "Images",
    "pdf_engine": "Engine",
    "api_engine": "API (fast, no login needed)",
    "browser_engine": "Browser (exact Notion look)",
    "engine_hint": "API = fast, no login, uses Design tab settings.\nBrowser = prints real Notion page (slower; needs login; ignores Design settings).",
    "sub_pages": "Sub-pages",
    "skip": "Skip",
    "inline": "Inline in parent",
    "separate": "Separate files",
    "depth": "Depth",
    "depth_hint": "How many levels of sub-pages to follow.",
    "sub_dbs": "Also export database rows inside pages (separate files mode)",
    "combined_file": "Also create one combined HTML / Markdown / LaTeX file",
    "markdown_flavour": "Markdown flavour",
    "github_flavored": "GFM",
    "vanilla": "Vanilla",
    "obsidian": "Obsidian",
    "database_extras": "Database extras",
    "none": "None",
    "index_page": "Index page",
    "table_props": "Table of properties",
    "csv_file": "CSV file",

    # Design tab
    "quick_style": "Quick style",
    "style_preset": "Style preset",
    "fonts": "Fonts",
    "body_font": "Body font",
    "heading_font": "Heading font",
    "google_fonts": "Download fonts from Google Fonts when needed (internet required)",
    "font_size": "Font size (px)",
    "line_spacing": "Line spacing",
    "text_alignment": "Text alignment",
    "title_alignment": "Title alignment",
    "color": "Color",
    "accent_color": "Accent color",
    "choose": "Choose…",
    "title_area": "Title area",
    "show_line": "Show a colored line under the page title",
    "page_icon": "Page icon",
    "custom_icon": "Custom icon file",
    "cover_page": "Cover page: title, icon and properties alone on page 1",
    "properties": "Properties (database fields)",
    "layout": "Layout",
    "table": "Notion Table",
    "pills": "Inline Pills",
    "list": "Minimalist List",
    "hidden": "Hidden",
    "date_format": "Date format",
    "load_properties": "Load properties",
    "show_these": "Show these",
    "tick_all": "Tick all",
    "untick_all": "Untick all",
    "content": "Content",
    "render_math": "Render math equations nicely (KaTeX)",
    "math_engine": "Math engine",
    "linked_pages": "Rewrite links between exported pages to local files",
    "expand_toggles": "Expand all toggle blocks",
    "links": "Links",
    "keep_links": "Keep all links",
    "remove_links": "Remove all links",
    "remove_internals": "Remove only Notion-internal links",
    "light_theme": "Force light theme (Browser engine only)",
    "clean_layout": "Hide Notion sidebar / top bar (Browser engine only)",
    "custom_css": "Custom CSS (for experts)",

    # Images tab
    "images_inside": "Images inside documents",
    "handling": "Handling",
    "embed": "Embed in file",
    "save_locally": "Save locally & link",
    "keep_link": "Keep Notion link",
    "optimize": "Shrink big photos for PDF / Word (faster export, smaller files)",
    "max_image_size": "Max image size (px)",
    "image_layout": "Image layout (PDF / HTML / Word)",
    "maximize": "Maximize images (full page width)",
    "one_per_page": "One image per page",
    "show_names": "Show image file names under images",
    "caption_format": "Caption format",
    "save_images": "Saving image files (tick \"Images\" in tab 3)",
    "file_name_format": "File name format",
    "image_examples": "Examples",
    "img_subfolder": "Put each page's images in its own folder",
    "img_cover": "Include page cover images",

    # PDF tab
    "page": "Page",
    "page_size": "Page size",
    "orientation": "Orientation",
    "portrait": "Portrait",
    "landscape": "Landscape",
    "margin": "Margin (mm)",
    "scale": "Scale (%)",
    "print_background": "Print background colors",
    "remove_blank": "Automatically remove empty pages",
    "page_numbers": "Add page numbers",
    "position": "Position",
    "bottom_center": "Bottom Center",
    "bottom_right": "Bottom Right",
    "top_right": "Top Right",
    "format": "Format",

    # LaTeX & AI tab
    "latex": "LaTeX (.tex)",
    "export_latex": "Export as LaTeX (.tex) document (compile with pdflatex or xelatex for Arabic)",
    "images_in_tex": "Images in .tex",
    "copy_latex": "📋 Copy last exported LaTeX",
    "clipboard_copy_done": "LaTeX document copied to clipboard!",
    "latex_not_ready": "No LaTeX export available yet. Run an export with 'LaTeX (.tex)' selected.",
    "gemini_ocr": "Gemini Math OCR — whiteboard photos → LaTeX",
    "key_note": "Each user enters their own key. Stored in OS keyring or config file.",
    "api_key": "Gemini API key",
    "show": "Show",
    "save": "Save",
    "get_key": "Get free key ↗",
    "scan_images": "Scan images with Gemini Math OCR",
    "model": "Model",
    "keep_whiteboard": "Keep a note of the original image below the transcription",

    # Output tab
    "output_folder": "Output folder (required)",
    "pdf_output": "PDF output",
    "merged_name": "Merged file name",
    "bookmarks": "Add bookmarks to the merged PDF",
    "speed_reliability": "Speed & reliability",
    "parallel_downloads": "Parallel downloads",
    "download_hint": "Pages and images are fetched in background while previous page renders. Notion limits (~3/s), so >4 rarely helps.",
    "incremental_sync": "Incremental sync: skip pages that did not change",
    "incremental_hint": "Uses Notion's last-edited time. Off automatically for combined files, inline sub-pages, raw image export.",
    "force_export": "Force full re-export (ignore the incremental cache)",
    "skip_existing": "Skip files already exported (resume interrupted export)",
    "retries": "Retries on failure",
    "extra_wait": "Extra wait per page (s)",
    "profile_timing": "Save timing_report.json with export profiling data",
    "browse": "Browse…",

    # Actions
    "export": "Export",
    "cancel": "Cancel",
    "copy_latex_action": "📋 Copy LaTeX",
    "about": "About / Beta",
    "done": "Done",
    "exported": "page(s)",
    "unchanged": "unchanged page(s) skipped",
    "force_reexport": "(tick \"Force full re-export\" to redo them)",
    "timing": "Timing",
    "problems": "problem(s)",
    "cancelled": "Cancelled. Files exported so far were kept.",
    "export_failed": "Export failed",

    # Dialogs
    "missing_info": "Missing info",
    "missing_info_msg": "Enter the Notion token and a database / page ID or URL.",
    "missing_folder": "Missing folder",
    "missing_folder_msg": "Choose an output folder on the Output tab.",
    "invalid_value": "Invalid value",
    "invalid_value_msg": "Check the numeric fields.",
    "no_pages_selected": "No pages ticked",
    "no_pages_msg": "Tick at least one page in tab 2, or clear the list by loading pages again.",
    "could_not_load_props": "Could not load properties",
    "could_not_load_pages": "Could not load pages",
    "preview_failed": "Preview failed",
    "choose_font": "Choose a font",
    "font_hint": "Search:",
    "no_font_selected": "No font selected",
    "use_this_font": "Use this font",
    "cancel_font": "Cancel",
    "choose_color": "Accent color (headings, links, quote bars)",
    "token_saved": "Key Saved",
    "secrets_not_saved": "Secrets not saved",
    "keyring_saving": "Keyring found: yes — secrets are stored in the OS credential store.",
    "no_keyring": "No OS keyring found (pip install keyring). Without it the token is not remembered unless you tick the box above.",

    # Status
    "nothing_selected": "(choose an output folder in tab 8)",
    "will_export": "Will export:",

    # Font picker
    "arabic_text": "The quick brown fox 0123456789  —  مرحبا بالعالم",
    "font_search": "Search:",
    "recommended": "Recommended (grey = not installed; Google Fonts need the option in Design tab)",
    "installed_ons_pc": "Installed on this PC",
    "generic": "Generic",
    "sans_serif": "Sans-serif",
    "serif": "Serif",
    "monospace": "Monospace",

    # Error messages
    "invalid_format": "Unknown format",
    "choose_formats": "Choose from:",
    "unknown_format": "Unknown format",
    "no_format_selected": "No format selected. Use --format, e.g. --format pdf,md",
    "no_token": "No Notion token. Set NOTION_TOKEN, store it in the app, or pass --token.",
    "nothing_to_export": "Nothing to export. Pass a page/database URL (or --zip).",
    "package_missing": "Package Missing",
    "genai_required": "The 'google-genai' library is required for Gemini Math OCR.",
    "genai_install": "Please install it with:\n  pip install google-genai",
    "gemini_key_required": "Gemini API Key Required",
    "gemini_key_missing": "Math OCR with Gemini Vision is enabled, but no Gemini API Key was entered.",
    "gemini_key_instructions": "Please enter your Gemini API key in the 'LaTeX & OCR' tab.",
    "gemini_key_link": "You can get a free key at:\nhttps://aistudio.google.com/",

    # Font families
    "same_as_body": "Same as body",
}

# Currently supported languages
SUPPORTED_LANGUAGES: Dict[str, Dict[str, str]] = {"en": EN}


def get_string(key: str, lang: Optional[str] = None) -> str:
    """Get a translated string by key."""
    lang_dict = SUPPORTED_LANGUAGES.get(lang, EN)
    return lang_dict.get(key, key)


def set_language(lang: str) -> None:
    """Set the current language (for future use)."""
    global _current_lang
    _current_lang = lang


_current_lang: Optional[str] = None


def _(key: str) -> str:
    """Translate a string. Used for future i18n support."""
    return get_string(key, _current_lang)