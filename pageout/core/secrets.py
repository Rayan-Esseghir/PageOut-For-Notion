from typing import Any

"""Secret storage (OS keyring) and redaction.

Tokens are kept in the OS keyring (Windows Credential Manager, macOS Keychain, Secret Service).
Writing them to ``config.json`` in plain text happens only when the user explicitly allows it
(``allow_plaintext_secrets``).
"""

import re

SERVICE = "PageOut for Notion"
SECRET_KEYS = {"token": "notion_token", "gemini_api_key": "gemini_api_key"}

_keyring: Any = None
try:  # pip install keyring   (optional)
    import keyring

    _keyring = keyring
except Exception:  # ImportError or a broken backend at import time
    _keyring = None


def keyring_available() -> bool:
    if _keyring is None:
        return False
    try:
        name = type(_keyring.get_keyring()).__module__
        return "fail" not in name and "null" not in name.lower()
    except Exception:
        return False


def get_secret(name: str) -> str:
    if not keyring_available():
        return ""
    try:
        return _keyring.get_password(SERVICE, name) or ""
    except Exception:
        return ""


def set_secret(name: str, value: str) -> bool:
    """Store (or delete, when value is empty) a secret. Returns True on success."""
    if not keyring_available():
        return False
    try:
        if value:
            _keyring.set_password(SERVICE, name, value)
        else:
            try:
                _keyring.delete_password(SERVICE, name)
            except Exception:
                pass
        return True
    except Exception:
        return False


_PATTERNS = [
    re.compile(r"\b(?:secret|ntn)_[A-Za-z0-9]{20,}"),  # Notion integration tokens
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),  # Google API keys
    re.compile(r"(?i)(authorization:\s*bearer\s+)\S+"),
]


def redact(text, secrets=()):
    """Remove known secrets and token-shaped strings from a message (logs, error reports)."""
    text = str(text)
    for sec in secrets:
        if sec and len(sec) >= 8:
            text = text.replace(sec, "***")
    for pat in _PATTERNS:
        text = pat.sub(lambda m: (m.group(1) + "***") if m.lastindex else "***", text)
    return text
