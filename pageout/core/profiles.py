"""Profile management for PageOut - named setting sets saved as JSON."""

import json
import os
from typing import Dict, List, Optional

from pageout.core.config import CONFIG_DIR, DEFAULTS

PROFILE_DIR = os.path.join(CONFIG_DIR, "profiles")


def ensure_profile_dir() -> None:
    """Ensure the profiles directory exists."""
    os.makedirs(PROFILE_DIR, exist_ok=True)


def list_profiles() -> List[str]:
    """Return list of profile names (without .json extension)."""
    ensure_profile_dir()
    try:
        return [f[:-5] for f in os.listdir(PROFILE_DIR) if f.endswith(".json")]
    except Exception:
        return []


def get_profile_path(name: str) -> str:
    """Get full path to a profile file."""
    ensure_profile_dir()
    # Sanitize name to prevent path traversal
    safe_name = "".join(c for c in name if c.isalnum() or c in ("-", "_", " ")).strip()
    return os.path.join(PROFILE_DIR, f"{safe_name}.json")


def save_profile(name: str, config: Dict) -> str:
    """Save a profile to disk.

    Args:
        name: Profile name
        config: Configuration dict (will be filtered to exclude secrets and runtime keys)

    Returns:
        Path to saved profile file
    """
    ensure_profile_dir()

    # Filter out secrets, internal keys, and runtime-specific settings
    # Runtime keys that should not be saved in profiles (they are provided at export time)
    RUNTIME_KEYS = {"database", "source_type", "token", "gemini_api_key"}

    profile_data = {}
    for key, value in config.items():
        if key in RUNTIME_KEYS:
            continue  # Never save secrets or runtime settings in profiles
        if key.startswith("_"):
            continue  # Skip internal keys
        profile_data[key] = value

    path = get_profile_path(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile_data, f, indent=2)
    return path


def load_profile(name: str) -> Dict:
    """Load a profile from disk.

    Args:
        name: Profile name

    Returns:
        Profile configuration dict

    Raises:
        FileNotFoundError: If profile doesn't exist
    """
    path = get_profile_path(name)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def delete_profile(name: str) -> bool:
    """Delete a profile.

    Returns:
        True if deleted, False if didn't exist
    """
    path = get_profile_path(name)
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False


def profile_exists(name: str) -> bool:
    """Check if a profile exists."""
    path = get_profile_path(name)
    return os.path.exists(path)


def merge_profile_into_config(profile_data: Dict, cfg: Dict) -> Dict:
    """Merge profile data into a config dict, using DEFAULTS for missing keys.

    Args:
        profile_data: Data loaded from profile
        cfg: Base config to merge into (will be modified)

    Returns:
        The modified cfg dict
    """
    for key, default in DEFAULTS.items():
        if key in profile_data:
            val = profile_data[key]
            if isinstance(default, bool):
                cfg[key] = bool(val)
            elif isinstance(default, int):
                cfg[key] = int(val)
            elif isinstance(default, float):
                cfg[key] = float(val)
            elif isinstance(default, list):
                cfg[key] = list(val) if val is not None else []
            else:
                cfg[key] = str(val)
    return cfg