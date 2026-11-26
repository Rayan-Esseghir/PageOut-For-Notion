"""Theme and styling support for the PageOut GUI.

This module provides:
- Light/dark/system theme switching
- HiDPI support
- Custom ttk styling
"""

import sys
from typing import Optional, Tuple

try:
    import tkinter as tk
    from tkinter import ttk
    import tkinter.font as tkfont
except ImportError:
    tk = None
    ttk = None
    tkfont = None


# Theme colors
LIGHT_THEMES = {
    "Notion Classic": {
        "bg": "#ffffff",
        "fg": "#000000",
        "accent": "#37352f",
        "header": "#f59e0b",
        "tab": "#e5e7eb",
        "tab_active": "#ffffff",
        "hint": "#6b7280",
        "button": "#f3f4f6",
    },
    "Modern Blue": {
        "bg": "#ffffff",
        "fg": "#000000",
        "accent": "#2563eb",
        "header": "#f59e0b",
        "tab": "#eff6ff",
        "tab_active": "#ffffff",
        "hint": "#6b7280",
        "button": "#f3f4f6",
    },
    "Clean Report": {
        "bg": "#ffffff",
        "fg": "#000000",
        "accent": "#0f766e",
        "header": "#f59e0b",
        "tab": "#f0fdf4",
        "tab_active": "#ffffff",
        "hint": "#6b7280",
        "button": "#f3f4f6",
    },
}

DARK_THEMES = {
    "Dark": {
        "bg": "#1f2937",
        "fg": "#f3f4f6",
        "accent": "#60a5fa",
        "header": "#f59e0b",
        "tab": "#374151",
        "tab_active": "#1f2937",
        "hint": "#9ca3af",
        "button": "#374151",
    },
}


class ThemeManager:
    """Manages GUI themes and styling."""

    def __init__(self, root):
        self.root = root
        self.current_theme = "light"  # light, dark, or system
        self.style = ttk.Style()
        self._configure_base_style()

    def _configure_base_style(self):
        """Set up base ttk styling that works across themes."""
        # Default font
        try:
            base_font = ("Segoe UI", 10) if sys.platform.startswith("win") else ("Helvetica", 10)
            self.style.configure(".", font=base_font)
        except Exception:
            pass

        # Common style configurations
        self.style.configure("Hint.TLabel", foreground="#6b7280", font=("", 9))
        self.style.configure("Head.TLabel", font=("", 15, "bold"))
        self.style.configure("Accent.TButton", font=("", 11, "bold"), padding=(18, 7))
        self.style.configure("TNotebook.Tab", padding=(11, 6))
        self.style.configure("TFrame", background=self.style.lookup("TFrame", "background") or "#ffffff")

    def apply_theme(self, theme_name: str = "light"):
        """Apply a theme by name."""
        self.current_theme = theme_name
        self._apply_light_theme() if theme_name == "light" else self._apply_dark_theme()

    def _apply_light_theme(self):
        """Apply light theme styling."""
        self.style.configure(".", background="#ffffff")
        # Keep default vista theme on Windows for best native look
        try:
            if sys.platform.startswith("win"):
                self.style.theme_use("vista")
        except Exception:
            pass

    def _apply_dark_theme(self):
        """Apply dark theme styling."""
        dark = DARK_THEMES.get("Dark", {})
        self.style.configure("TFrame", background=dark.get("bg", "#1f2937"))
        self.style.configure("TLabel", background=dark.get("bg", "#1f2937"), foreground=dark.get("fg", "#f3f4f6"))
        # Note: ttk widgets like ttk.Button don't easily support dark themes
        # The root window handles dark mode via background color

    def is_dark(self) -> bool:
        """Check if current theme is dark."""
        return self.current_theme == "dark"

    def supports_system_theme(self) -> bool:
        """Check if we can detect system theme preference."""
        # On Windows 10+, we could check registry
        # For now, return False - user preference takes precedence
        return False

    def get_accent_color(self) -> str:
        """Get the current accent color for the active theme."""
        if self.current_theme == "dark":
            return DARK_THEMES["Dark"].get("accent", "#60a5fa")
        return "#37352f"  # Default accent


class HiDPISupport:
    """HiDPI screen support utilities."""

    @staticmethod
    def enable(root) -> None:
        """Enable HiDPI awareness for the given root window."""
        if sys.platform != "win32":
            return

        try:
            import ctypes

            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def get_font_family(installed_fonts: set, font_name: str) -> Optional[str]:
    """Get the actual font family to use for a font name.

    Returns None if the font is not installed.
    """
    generic_aliases = {
        "Sans-serif": "Helvetica",
        "Serif": "Times",
        "Monospace": "Courier",
        "Same as body": None,  # Will be determined from body font
    }

    if font_name in generic_aliases:
        alias = generic_aliases[font_name]
        if alias is None:
            return None  # "Same as body" - caller handles this
        if alias in installed_fonts or font_name in generic_aliases:
            return alias
        return None

    if font_name in installed_fonts:
        return font_name
    return None  # Not installed


def get_available_fonts(root) -> Tuple[set, list]:
    """Get set of installed fonts and list of available font families."""
    try:
        installed = {f for f in tkfont.families(root) if not f.startswith("@")}
    except Exception:
        installed = set()

    # Get recommended fonts (common on most systems + popular Google Fonts)
    return installed, ["Sans-serif", "Serif", "Monospace"]