"""Resource paths (works as .py and as PyInstaller .exe)."""

import os
import sys
from pathlib import Path


def _resource_dir() -> Path:
    """Return the directory where bundled resources live (or the script dir)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent.parent  # project root (contains icon.ico)


RESOURCE_DIR = _resource_dir()


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


def resource_path(rel: str) -> Path:
    """Resolve a resource path that works both as .py and compiled .exe."""
    return RESOURCE_DIR / rel


_setup_portable_browsers()
