"""U7: Safety, i18n, accessibility & final build support.

Provides:
- Confirmations for overwrite, large exports, cloud-synced folders, long paths
- Crash/session recovery
- High-contrast theme, keyboard-only operation, accessible widget names
- Complete English + Arabic RTL UI
"""

import json
import os
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Safety confirmations
# ---------------------------------------------------------------------------


@dataclass
class SafetyCheck:
    """Represents a single safety check result."""

    check_type: str  # "overwrite", "large_export", "cloud_folder", "long_path"
    requires_confirmation: bool
    message: str = ""
    details: dict = field(default_factory=dict)


def check_overwrite(output_dir: str, cfg: dict) -> SafetyCheck:
    """Check if export will overwrite existing files."""
    if not output_dir or not os.path.isdir(output_dir):
        return SafetyCheck("overwrite", False)

    existing = []
    for root, dirs, files in os.walk(output_dir):
        for f in files:
            existing.append(os.path.join(root, f))

    if existing and not cfg.get("skip_existing", False):
        return SafetyCheck(
            "overwrite",
            True,
            f"Output folder contains {len(existing)} existing file(s). Export may overwrite them.",
            {"existing_count": len(existing), "files": existing[:10]},
        )
    return SafetyCheck("overwrite", False)


def estimate_export_time(page_count: int, cfg: dict) -> int:
    """Estimate export time in minutes based on page count and settings."""
    base_per_page = 2.0  # seconds
    if cfg.get("engine", "").startswith("Browser"):
        base_per_page = 8.0
    if cfg.get("fmt_pdf"):
        base_per_page += 3.0
    if cfg.get("fmt_images"):
        base_per_page += 1.5

    total_seconds = page_count * base_per_page
    return max(1, int(total_seconds / 60))


def check_large_export(page_count: int, cfg: dict) -> SafetyCheck:
    """Check if export is large enough to warrant confirmation."""
    threshold_mb = cfg.get("prefs_large_export_threshold_mb", 500)
    estimated_minutes = estimate_export_time(page_count, cfg)

    # Consider large if many pages or long estimated time
    if page_count > 100 or estimated_minutes > 30:
        return SafetyCheck(
            "large_export",
            True,
            f"This export contains {page_count} page(s) and may take ~{estimated_minutes} minute(s). Continue?",
            {"page_count": page_count, "estimated_minutes": estimated_minutes},
        )
    return SafetyCheck("large_export", False)


CLOUD_FOLDER_PATTERNS = [
    "onedrive",
    "dropbox",
    "google drive",
    "googledrive",
    "icloud",
    "nextcloud",
    "sync",
]


def is_cloud_synced_folder(path: str) -> bool:
    """Detect if a path is inside a cloud-synced folder."""
    if not path:
        return False
    lower = path.lower()
    return any(p in lower for p in CLOUD_FOLDER_PATTERNS)


def check_cloud_folder(output_dir: str) -> SafetyCheck:
    """Check if output folder is cloud-synced."""
    if is_cloud_synced_folder(output_dir):
        return SafetyCheck(
            "cloud_folder",
            True,
            f"Output folder appears to be cloud-synced ({output_dir}). Files may sync slowly or conflict. Continue?",
            {"path": output_dir},
        )
    return SafetyCheck("cloud_folder", False)


def is_long_path(path: str, max_length: int = 240) -> bool:
    """Check if a path exceeds Windows long-path threshold."""
    return len(path) > max_length


def check_long_path(output_dir: str, cfg: dict, max_length: int = 240) -> SafetyCheck:
    """Check if output path may exceed Windows path limits."""
    if not cfg.get("prefs_enable_long_paths", True):
        return SafetyCheck("long_path", False)

    if is_long_path(output_dir, max_length):
        return SafetyCheck(
            "long_path",
            True,
            f"Output path is very long ({len(output_dir)} chars). "
            "Some files may fail to save. Consider a shorter path.",
            {"path": output_dir, "length": len(output_dir)},
        )
    return SafetyCheck("long_path", False)


def run_safety_checks(output_dir: str, page_count: int, cfg: dict) -> list:
    """Run all safety checks and return those requiring confirmation."""
    checks = [
        check_overwrite(output_dir, cfg),
        check_large_export(page_count, cfg),
        check_cloud_folder(output_dir),
        check_long_path(output_dir, cfg),
    ]
    return [c for c in checks if c.requires_confirmation]


# ---------------------------------------------------------------------------
# Crash / Session Recovery
# ---------------------------------------------------------------------------

SESSION_DIR = os.path.join(os.path.expanduser("~"), ".notion_pdf_exporter")
SESSION_FILE = os.path.join(SESSION_DIR, "session.json")
SESSION_BACKUP = os.path.join(SESSION_DIR, "session.backup.json")


@dataclass
class ExportSession:
    """Represents an in-progress or interrupted export session."""

    session_id: str
    started_at: float
    source: str
    output_dir: str
    formats: list
    pages_total: int = 0
    pages_done: int = 0
    pages_failed: list = field(default_factory=list)
    status: str = "running"  # running, completed, interrupted, failed
    config_snapshot: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "source": self.source,
            "output_dir": self.output_dir,
            "formats": self.formats,
            "pages_total": self.pages_total,
            "pages_done": self.pages_done,
            "pages_failed": self.pages_failed,
            "status": self.status,
            "config_snapshot": self.config_snapshot,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExportSession":
        return cls(
            session_id=data.get("session_id", ""),
            started_at=data.get("started_at", 0),
            source=data.get("source", ""),
            output_dir=data.get("output_dir", ""),
            formats=data.get("formats", []),
            pages_total=data.get("pages_total", 0),
            pages_done=data.get("pages_done", 0),
            pages_failed=data.get("pages_failed", []),
            status=data.get("status", "interrupted"),
            config_snapshot=data.get("config_snapshot", {}),
        )


def save_session(session: ExportSession) -> bool:
    """Save current export session to disk for crash recovery."""
    try:
        os.makedirs(SESSION_DIR, exist_ok=True)
        # Backup existing
        if os.path.exists(SESSION_FILE):
            try:
                with open(SESSION_FILE, "r", encoding="utf-8") as f:
                    old = f.read()
                with open(SESSION_BACKUP, "w", encoding="utf-8") as f:
                    f.write(old)
            except Exception:
                pass
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(session.to_dict(), f, indent=2)
        return True
    except Exception:
        return False


def load_session() -> Optional[ExportSession]:
    """Load the last saved session, if any."""
    for path in (SESSION_FILE, SESSION_BACKUP):
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return ExportSession.from_dict(data)
        except Exception:
            continue
    return None


def clear_session() -> bool:
    """Clear saved session after successful completion."""
    try:
        for path in (SESSION_FILE, SESSION_BACKUP):
            if os.path.exists(path):
                os.remove(path)
        return True
    except Exception:
        return False


def has_interrupted_session() -> bool:
    """Check if there's an interrupted session to recover."""
    session = load_session()
    if session and session.status in ("running", "interrupted"):
        return True
    return False


def recover_session_prompt() -> Optional[ExportSession]:
    """Get interrupted session for user prompt."""
    session = load_session()
    if session and session.status in ("running", "interrupted"):
        return session
    return None


# ---------------------------------------------------------------------------
# Accessibility helpers
# ---------------------------------------------------------------------------


def accessible_name(widget_key: str, lang: str = "en") -> str:
    """Get an accessible name for a widget based on its key."""
    from pageout.gui.i18n import get_string

    return get_string(widget_key, lang)


def set_accessible_name(widget, name: str) -> None:
    """Set accessible name on a Tk widget (if supported)."""
    try:
        widget.winfo_toplevel().update_idletasks()
    except Exception:
        pass
    # Tkinter doesn't have native accessible name, but we can set it as a tooltip/description
    try:
        widget._accessible_name = name
    except Exception:
        pass


def is_rtl_language(lang: str) -> bool:
    """Check if language requires RTL layout."""
    # For direct checks, use inline logic
    return lang in ("ar", "he", "fa", "ur")


# ---------------------------------------------------------------------------
# High-contrast theme
# ---------------------------------------------------------------------------

HIGH_CONTRAST_COLORS = {
    "bg": "#000000",
    "fg": "#FFFFFF",
    "select_bg": "#FFFFFF",
    "select_fg": "#000000",
    "button_bg": "#000000",
    "button_fg": "#FFFFFF",
    "entry_bg": "#000000",
    "entry_fg": "#FFFFFF",
    "accent": "#FFFF00",
}


def apply_high_contrast(root) -> None:
    """Apply high-contrast theme to a Tk root window."""
    from tkinter import ttk

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    colors = HIGH_CONTRAST_COLORS
    root.configure(bg=colors["bg"])
    style.configure(".", background=colors["bg"], foreground=colors["fg"])
    style.configure("TButton", background=colors["button_bg"], foreground=colors["button_fg"])
    style.configure("TLabel", background=colors["bg"], foreground=colors["fg"])
    style.configure("TCheckbutton", background=colors["bg"], foreground=colors["fg"])
    style.configure("TRadiobutton", background=colors["bg"], foreground=colors["fg"])
    style.configure("TEntry", fieldbackground=colors["entry_bg"], foreground=colors["entry_fg"])
    style.configure("TCombobox", fieldbackground=colors["entry_bg"], foreground=colors["entry_fg"])


# ---------------------------------------------------------------------------
# Keyboard navigation helpers
# ---------------------------------------------------------------------------


def setup_keyboard_navigation(root) -> None:
    """Setup keyboard-only navigation helpers."""

    # Tab order is handled by Tk, but we ensure all widgets are focusable
    def cycle_focus(event):
        # Get all focusable widgets
        widgets = []
        for child in root.winfo_children():
            _collect_focusable(child, widgets)
        if not widgets:
            return
        current = root.focus_get()
        try:
            idx = widgets.index(current)
            next_idx = (idx + 1) % len(widgets)
        except ValueError:
            next_idx = 0
        widgets[next_idx].focus_set()
        return "break"

    root.bind("<F6>", cycle_focus)


def _collect_focusable(widget, result: list) -> None:
    """Recursively collect focusable widgets."""
    try:
        if widget.winfo_takefocus():
            result.append(widget)
    except Exception:
        pass
    try:
        for child in widget.winfo_children():
            _collect_focusable(child, result)
    except Exception:
        pass
