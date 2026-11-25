"""Test setup: make the app importable and stub heavy optional deps so tests run headless."""

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


try:
    import notion_client  # noqa: F401
except ImportError:

    class _Client:
        def __init__(self, *a, **k):
            pass

    _stub("notion_client", Client=_Client)

try:
    import playwright.sync_api  # noqa: F401
except ImportError:

    def _no_pw():
        raise RuntimeError("Playwright is stubbed in tests (PDF is not covered by Phase 0)")

    _stub("playwright")
    _stub("playwright.sync_api", sync_playwright=_no_pw)

import base64

import pytest

# two different 2x2 PNGs so tests can tell images apart (and test de-duplication)
_PNGS = [
    base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGO8o6HBwMDAxMDAwMDAAAAO7gEwnDTINgAAAABJRU5ErkJggg=="
    ),
    base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGPUWGDDwMDAxMDAwMDAAAAMRgEI1mFy2QAAAABJRU5ErkJggg=="
    ),
]


def png_for(url: str) -> bytes:
    return _PNGS[sum(map(ord, url)) % 2]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Tests never touch the network: image downloads return a tiny PNG chosen by URL."""
    import pageout.core.pipeline as pipeline
    import pageout.ocr.gemini as gemini

    fake = lambda url, timeout=60: (png_for(url), "image/png")  # noqa: E731
    monkeypatch.setattr(pipeline, "download", fake)
    monkeypatch.setattr(gemini, "download", fake)


@pytest.fixture(autouse=True)
def _fake_keyring(monkeypatch):
    """In-memory keyring so tests never touch the real OS credential store."""
    import pageout.core.secrets as secrets

    store = {}
    monkeypatch.setattr(secrets, "keyring_available", lambda: True)
    monkeypatch.setattr(secrets, "get_secret", lambda name: store.get(name, ""))

    def _set(name, value):
        if value:
            store[name] = value
        else:
            store.pop(name, None)
        return True

    monkeypatch.setattr(secrets, "set_secret", _set)
    return store
