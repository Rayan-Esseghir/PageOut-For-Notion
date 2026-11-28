"""Source management for PageOut - saved Notion database/page sources as named entries.

This module provides functions to save, load, and manage Notion sources
(database IDs, page URLs, or URLs) in a JSON file, similar to the profiles pattern.
"""

import json
import os
import re
from typing import Dict, List, Optional

from pageout.core.config import CONFIG_DIR, SOURCE_TYPES

SOURCE_DIR = os.path.join(CONFIG_DIR, "sources")

# Regex to extract 32-hex ID from Notion URLs
_ID_RE = re.compile(r"([0-9a-fA-F]{32})(?:[?#].*)?$")

# Regex to extract workspace ID from Notion URLs (13-character base-36 string)
_WORKSPACE_RE = re.compile(r"([A-Za-z0-9]{13})(?:[?#].*)?$")

# Regex to extract all 32-hex IDs from URLs (for multi-source support)
_MULTI_ID_RE = re.compile(r"([0-9a-fA-F]{32})")


def ensure_source_dir() -> None:
    """Ensure the sources directory exists."""
    os.makedirs(SOURCE_DIR, exist_ok=True)


def get_source_path(name: str) -> str:
    """Get full path to a source file.

    Sanitizes the name to prevent path traversal attacks.
    """
    ensure_source_dir()
    safe_name = "".join(c for c in name if c.isalnum() or c in ("-", "_", " ")).strip()
    if not safe_name:
        raise ValueError("Invalid source name")
    return os.path.join(SOURCE_DIR, f"{safe_name}.json")


def extract_id_from_url(url: str) -> Optional[str]:
    """Extract Notion page/database ID from a URL or raw ID.

    Args:
        url: A Notion URL (page or database) or raw 32-hex ID

    Returns:
        The extracted 32-character lowercase hex ID, or None if not a valid ID/URL
    """
    if not url:
        return None

    url_clean = url.replace("-", "")

    # Check if it's a bare 32-hex ID
    if re.fullmatch(r"[0-9a-fA-F]{32}", url_clean):
        return url_clean.lower()

    # Try to extract ID from URL
    m = _ID_RE.search(url_clean)
    if m:
        return m.group(1).lower()

    return None


def list_sources() -> List[Dict]:
    """Return list of all saved sources.

    Each source dict contains:
        - name: The source name
        - url: The Notion URL or ID
        - workspace: (optional) The workspace ID
        - source_type: One of SOURCE_TYPES values
        - pinned: Whether the source is pinned (defaults to False)
        - filter_prop: Property to filter by (optional)
        - filter_op: Filter operator (optional)
        - filter_value: Filter value (optional)
        - sort_by: Sort property (optional)
        - sort_desc: Sort descending (optional)
        - max_pages: Max pages limit (optional)
        - group_by: Property to group by for group-based export (optional)
        - sources: List of additional source URLs/IDs (for multi-source databases)

    Returns:
        List of source dictionaries, sorted by name
    """
    ensure_source_dir()
    sources = []
    try:
        for f in os.listdir(SOURCE_DIR):
            if f.endswith(".json"):
                try:
                    with open(os.path.join(SOURCE_DIR, f), "r", encoding="utf-8") as fp:
                        src = json.load(fp)
                        # Ensure all required fields exist for backward compatibility
                        src.setdefault("pinned", False)
                        src.setdefault("source_type", SOURCE_TYPES[0])
                        # Phase 11: Add new fields with defaults
                        src.setdefault("workspace", "")
                        src.setdefault("filter_prop", "")
                        src.setdefault("filter_op", "contains")
                        src.setdefault("filter_value", "")
                        src.setdefault("sort_by", "Date")
                        src.setdefault("sort_desc", False)
                        src.setdefault("max_pages", 0)
                        src.setdefault("group_by", "")
                        src.setdefault("sources", [])
                        sources.append(src)
                except Exception:
                    continue  # Skip malformed files
    except Exception:
        pass

    # Sort by name
    sources.sort(key=lambda x: x.get("name", "").lower())
    return sources


def source_exists(name: str) -> bool:
    """Check if a source with the given name exists.

    Args:
        name: The source name to check

    Returns:
        True if the source exists, False otherwise
    """
    try:
        path = get_source_path(name)
        return os.path.exists(path)
    except Exception:
        return False


def get_source(name: str) -> Optional[Dict]:
    """Get a specific source by name.

    Args:
        name: The source name

    Returns:
        Source dict, or None if not found
    """
    try:
        path = get_source_path(name)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                src = json.load(f)
                # Ensure all required fields exist for backward compatibility
                src.setdefault("pinned", False)
                src.setdefault("source_type", SOURCE_TYPES[0])
                # Phase 11: Add new fields with defaults
                src.setdefault("workspace", "")
                src.setdefault("filter_prop", "")
                src.setdefault("filter_op", "contains")
                src.setdefault("filter_value", "")
                src.setdefault("sort_by", "Date")
                src.setdefault("sort_desc", False)
                src.setdefault("max_pages", 0)
                src.setdefault("group_by", "")
                src.setdefault("sources", [])
                return src
    except Exception:
        pass
    return None


def add_source(
    name: str,
    url: str = "",
    source_type: str = "Auto-detect",
    pinned: bool = False,
    workspace: str = "",
    filter_prop: str = "",
    filter_op: str = "contains",
    filter_value: str = "",
    sort_by: str = "Date",
    sort_desc: bool = False,
    max_pages: int = 0,
    group_by: str = "",
    sources: Optional[List[str]] = None,
) -> str:
    """Save a new source.

    Args:
        name: The source name
        url: The Notion URL or ID
        source_type: One of SOURCE_TYPES values (default: "Auto-detect")
        pinned: Whether to pin this source (default: False)
        workspace: The workspace ID (for Phase 11 workspace navigation)
        filter_prop: Property to filter by (for Phase 11)
        filter_op: Filter operator (contains, does not contain, equals)
        filter_value: Filter value
        sort_by: Sort property
        sort_desc: Sort descending
        max_pages: Maximum pages to export (0 = no limit)
        group_by: Property to group by for group-based export
        sources: List of additional source URLs/IDs (for multi-source databases)

    Returns:
        Path to the saved source file

    Raises:
        ValueError: If name is invalid
    """
    ensure_source_dir()

    # Validate source_type
    if source_type not in SOURCE_TYPES:
        source_type = SOURCE_TYPES[0]

    # Normalize filter_op to a valid value
    valid_ops = ["contains", "does not contain", "equals"]
    if filter_op not in valid_ops:
        filter_op = "contains"

    # Normalize sort_by
    valid_sorts = ["Date", "Title", "Created", "Last edited", "Database order"]
    if sort_by not in valid_sorts:
        sort_by = "Date"

    source_data = {
        "name": name,
        "url": url or "",
        "workspace": workspace or "",
        "source_type": source_type,
        "pinned": bool(pinned),
        "filter_prop": filter_prop or "",
        "filter_op": filter_op,
        "filter_value": filter_value or "",
        "sort_by": sort_by,
        "sort_desc": bool(sort_desc),
        "max_pages": int(max_pages),
        "group_by": group_by or "",
        "sources": sources or [],
    }

    path = get_source_path(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(source_data, f, indent=2)

    return path


def delete_source(name: str) -> bool:
    """Delete a source by name.

    Args:
        name: The source name to delete

    Returns:
        True if deleted, False if it didn't exist
    """
    try:
        path = get_source_path(name)
        if os.path.exists(path):
            os.remove(path)
            return True
    except Exception:
        pass
    return False


def toggle_pin(name: str) -> bool:
    """Toggle the pinned status of a source.

    Args:
        name: The source name

    Returns:
        The new pinned status (True if now pinned, False if unpinned)

    Raises:
        FileNotFoundError: If source doesn't exist
    """
    src = get_source(name)
    if src is None:
        raise FileNotFoundError(f"Source '{name}' not found")

    new_status = not src.get("pinned", False)
    src["pinned"] = new_status

    path = get_source_path(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(src, f, indent=2)

    return new_status


def update_source(name: str, **kwargs) -> bool:
    """Update a source's settings.

    Args:
        name: The source name
        **kwargs: Fields to update (url, source_type, pinned, filter_prop, filter_op,
                  filter_value, sort_by, sort_desc, max_pages, group_by, sources, workspace)

    Returns:
        True if updated successfully, False if source not found
    """
    from pageout.sources.notion_api import normalize_source_ids

    src = get_source(name)
    if src is None:
        return False

    valid_fields = {
        "url",
        "source_type",
        "pinned",
        "workspace",
        "filter_prop",
        "filter_op",
        "filter_value",
        "sort_by",
        "sort_desc",
        "max_pages",
        "group_by",
        "sources",
    }

    for key, value in kwargs.items():
        if key in valid_fields:
            if key == "pinned" or key == "sort_desc":
                src[key] = bool(value)
            elif key == "max_pages":
                src[key] = int(value)
            elif key == "sources":
                # Normalize sources to a list of valid IDs
                src[key] = normalize_source_ids(value)
            else:
                src[key] = value

    path = get_source_path(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(src, f, indent=2)

    return True


def get_recent_sources(limit: int = 10) -> List[Dict]:
    """Get recent sources, with pinned sources first.

    Args:
        limit: Maximum number of sources to return (default: 10)

    Returns:
        List of sources, pinned ones first, sorted by name, limited to 'limit' items
    """
    sources = list_sources()

    # Sort: pinned first, then by name
    sources.sort(key=lambda x: (not x.get("pinned", False), x.get("name", "").lower()))

    return sources[:limit]


def extract_workspace_id(url: str) -> str:
    """Extract Notion workspace ID from a URL.

    Workspace IDs are 13-character base-36 strings in Notion URLs.
    Example: https://www.notion.so/workspace-name-0123456789abc

    Args:
        url: A Notion URL

    Returns:
        The extracted 13-character workspace ID, or empty string if not found
    """
    if not url:
        return ""

    # Try to extract workspace ID from URL
    m = _WORKSPACE_RE.search(url.replace("-", ""))
    if m:
        return m.group(1).lower()

    # Also try with dashes (base-36 can include letters)
    m = _WORKSPACE_RE.search(url)
    if m:
        return m.group(1).lower()

    return ""


def extract_all_ids(url: str) -> List[str]:
    """Extract all 32-hex IDs from a URL.

    This is useful for multi-source URLs that contain multiple page/database IDs.

    Args:
        url: A Notion URL

    Returns:
        List of extracted IDs (lowercase, without hyphens)
    """
    if not url:
        return []

    return [m.group(1).lower() for m in _MULTI_ID_RE.finditer(url.replace("-", ""))]


def build_source_from_url(url: str, name: str | None = None, source_type: str = "Auto-detect") -> Dict:
    """Build a source dictionary from a URL, extracting all relevant IDs.

    Args:
        url: A Notion URL
        name: Optional source name (defaults to extracted from URL)
        source_type: Source type

    Returns:
        Source dictionary with extracted IDs
    """
    ids = extract_all_ids(url)
    workspace = extract_workspace_id(url)

    if not name:
        # Try to get name from URL
        path_match = re.search(r"/([^/]+)/?$", url.replace("-", ""))
        if path_match:
            name = path_match.group(1)[:50]
        else:
            name = f"Source-{ids[0][:8] if ids else 'unknown'}"

    src = {
        "name": name,
        "url": ids[0] if ids else url,
        "sources": ids[1:] if len(ids) > 1 else [],
        "workspace": workspace,
        "source_type": source_type,
        "pinned": False,
        "filter_prop": "",
        "filter_op": "contains",
        "filter_value": "",
        "sort_by": "Date",
        "sort_desc": False,
        "max_pages": 0,
        "group_by": "",
    }

    return src


def search_sources_by_workspace(workspace_id: str) -> List[Dict]:
    """Search for sources belonging to a specific workspace.

    Args:
        workspace_id: The workspace ID to search for

    Returns:
        List of sources belonging to the workspace
    """
    sources = list_sources()
    return [s for s in sources if s.get("workspace", "").lower() == workspace_id.lower()]


def get_sources_with_filter() -> List[Dict]:
    """Get sources that have filter settings configured.

    Returns:
        List of sources with non-empty filter settings
    """
    sources = list_sources()
    return [s for s in sources if s.get("filter_prop") or s.get("filter_value") or s.get("sort_by") != "Date"]


__all__ = [
    "list_sources",
    "get_source",
    "add_source",
    "delete_source",
    "toggle_pin",
    "get_recent_sources",
    "extract_id_from_url",
    "source_exists",
    "get_sources_with_filter",
    "search_sources_by_workspace",
    "build_source_from_url",
    "extract_workspace_id",
    "extract_all_ids",
]
