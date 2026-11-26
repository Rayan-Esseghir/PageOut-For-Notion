"""Source management for PageOut - saved databases/pages with searchable dropdown."""

import json
import os
import re
from typing import Dict, List, Optional, Any

from pageout.core.config import CONFIG_DIR

SOURCES_FILE = os.path.join(CONFIG_DIR, "sources.json")


def ensure_sources_file() -> None:
    """Ensure the sources file exists with default structure."""
    if not os.path.exists(SOURCES_FILE):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(SOURCES_FILE, "w", encoding="utf-8") as f:
            json.dump({"sources": []}, f, indent=2)


def _load_sources_data() -> Dict:
    """Load sources data from file."""
    ensure_sources_file()
    try:
        with open(SOURCES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"sources": []}


def _save_sources_data(data: Dict) -> None:
    """Save sources data to file."""
    ensure_sources_file()
    try:
        with open(SOURCES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def list_sources() -> List[Dict]:
    """Return list of all saved sources."""
    data = _load_sources_data()
    return data.get("sources", [])


def get_source(name: str) -> Optional[Dict]:
    """Get a source by name."""
    for src in list_sources():
        if src.get("name") == name:
            return src
    return None


def source_exists(name: str) -> bool:
    """Check if a source exists."""
    return get_source(name) is not None


def add_source(name: str, url: str, source_type: str = "Auto-detect", pinned: bool = False) -> bool:
    """Add or update a source.

    Args:
        name: Unique name for the source
        url: Notion database/page URL or ID
        source_type: One of "Auto-detect", "Database", "Page"
        pinned: Whether to pin this source (shows at top)

    Returns:
        True if added/updated, False if failed
    """
    # Validate source_type
    valid_types = ["Auto-detect", "Database", "Page"]
    if source_type not in valid_types:
        source_type = "Auto-detect"

    data = _load_sources_data()
    sources = data.get("sources", [])

    # Remove existing source with same name
    sources = [s for s in sources if s.get("name") != name]

    # Add new source at the beginning (most recent first)
    new_source = {
        "name": name,
        "url": url,
        "source_type": source_type,
        "pinned": pinned,
    }
    sources.insert(0, new_source)

    # Limit to reasonable number
    if len(sources) > 50:
        # Keep pinned + most recent unpinned
        pinned_sources = [s for s in sources if s.get("pinned")]
        unpinned = [s for s in sources if not s.get("pinned")]
        sources = pinned_sources + unpinned[:50 - len(pinned_sources)]

    data["sources"] = sources
    _save_sources_data(data)
    return True


def delete_source(name: str) -> bool:
    """Delete a source by name.

    Returns:
        True if deleted, False if didn't exist
    """
    data = _load_sources_data()
    sources = data.get("sources", [])
    original_len = len(sources)
    sources = [s for s in sources if s.get("name") != name]
    if len(sources) < original_len:
        data["sources"] = sources
        _save_sources_data(data)
        return True
    return False


def toggle_pin(name: str) -> bool:
    """Toggle pinned status of a source.

    Returns:
        New pinned status, or False if source not found
    """
    data = _load_sources_data()
    sources = data.get("sources", [])
    for src in sources:
        if src.get("name") == name:
            src["pinned"] = not src.get("pinned", False)
            data["sources"] = sources
            _save_sources_data(data)
            return src["pinned"]
    return False


def get_recent_sources(limit: int = 10) -> List[Dict]:
    """Get recent sources (unpinned, most recent first)."""
    sources = list_sources()
    # Sort: pinned first, then by order (most recent first)
    pinned = [s for s in sources if s.get("pinned")]
    unpinned = [s for s in sources if not s.get("pinned")]
    return pinned + unpinned[:limit]


def extract_id_from_url(url: str) -> Optional[str]:
    """Extract Notion page/database ID from URL.

    Supports formats:
    - https://www.notion.so/workspace/Page-Title-1234567890abcdef1234567890abcdef
    - https://www.notion.so/1234567890abcdef1234567890abcdef
    - https://www.notion.so/1234567890abcdef1234567890abcdef?v=...
    - Just the ID: 1234567890abcdef1234567890abcdef
    """
    # If it's already a bare ID (32 hex chars)
    if re.match(r'^[a-f0-9]{32}$', url, re.IGNORECASE):
        return url

    # Try to extract from URL
    # Pattern: 32 hex chars at the end of path or before query
    match = re.search(r'([a-f0-9]{32})(?:[?#]|$)', url, re.IGNORECASE)
    if match:
        return match.group(1)

    return None