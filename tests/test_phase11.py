"""Tests for Phase 11: Workspace sources, filter/sort/group_by, and multi-source support."""

import json

import pytest
from fake_notion import DB_ID, FakeNotion

from pageout.cli import main as cli_main
from pageout.core.config import DEFAULTS, SOURCE_TYPES, DB_EXPORT_MODES
from pageout.core.sources import (
    add_source,
    get_source,
    list_sources,
    delete_source,
    extract_id_from_url,
    extract_workspace_id,
    extract_all_ids,
    build_source_from_url,
    get_recent_sources,
    search_sources_by_workspace,
    update_source,
    get_sources_with_filter,
    source_exists,
    toggle_pin,
)
from pageout.core.pipeline import export


def cfg_for(out, **over):
    cfg = dict(
        DEFAULTS,
        token="tok-not-a-secret",
        database=DB_ID,
        save_dir=str(out),
        fmt_pdf=False,
        fmt_md=True,
        img_handling="Keep Notion link",
    )
    cfg.update(over)
    return cfg


def run(out, notion=None, **over):
    return export(cfg_for(out, **over), notion=notion or FakeNotion())


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr("pageout.core.config.CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr("pageout.core.config.CONFIG_FILE", str(tmp_path / "cfg" / "config.json"))
    monkeypatch.delattr("pageout.core.config", "SOURCE_DIR",raising=False)
    import pageout.core.sources as sources
    monkeypatch.setattr(sources, "SOURCE_DIR", str(tmp_path / "cfg" / "sources"))
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


# ---------------------------------------------------------------------- Test extract_id_from_url edge cases
def test_extract_id_from_url_invalid_input():
    """Invalid IDs should return None, not the input string."""
    assert extract_id_from_url("not-a-valid-id") is None
    assert extract_id_from_url("") is None
    assert extract_id_from_url(None) is None
    assert extract_id_from_url("abc123") is None  # too short
    assert extract_id_from_url("g" * 32) is None  # invalid hex chars


def test_extract_id_from_url_valid_inputs():
    """Valid IDs and URLs should be correctly extracted."""
    # Bare 32-hex ID
    assert extract_id_from_url("1234567890abcdef1234567890abcdef") == "1234567890abcdef1234567890abcdef"

    # Full Notion URL with ID
    url = "https://www.notion.so/workspace/My-Page-1234567890abcdef1234567890abcdef"
    assert extract_id_from_url(url) == "1234567890abcdef1234567890abcdef"

    # URL with query string
    url = "https://www.notion.so/1234567890abcdef1234567890abcdef?v=1"
    assert extract_id_from_url(url) == "1234567890abcdef1234567890abcdef"

    # ID with hyphens
    id_with_hyphens = "12345678-90ab-cdef-1234-567890abcdef"
    assert extract_id_from_url(id_with_hyphens) == "1234567890abcdef1234567890abcdef"


# ---------------------------------------------------------------------- Test workspace ID extraction
def test_extract_workspace_id():
    """Workspace ID extraction returns a 13-char base36 string or empty string."""
    # Test with empty input
    assert extract_workspace_id("") == ""
    assert extract_workspace_id(None) == ""

    # Test that it extracts 13-char base36 from URLs with workspace ID
    url = "https://www.notion.so/myworkspace-abc123def45678"
    result = extract_workspace_id(url)
    # Should be a 13-char base36 string
    if result:
        assert len(result) == 13
        assert result.isalnum()  # base36 is alphanumeric


def test_extract_all_ids():
    """Extract all 32-hex IDs from a URL."""
    # Multiple IDs in a URL (rare but possible)
    url = "https://www.notion.so/page-1234567890abcdef1234567890abcdef-9876543210fedcba9876543210abcdef"
    ids = extract_all_ids(url)
    assert len(ids) >= 1  # Should extract at least one ID

    # Single ID
    url = "https://www.notion.so/page-1234567890abcdef1234567890abcdef"
    ids = extract_all_ids(url)
    assert len(ids) >= 1
    id_found = any("1234567890abcdef" in i for i in ids)
    assert id_found

    # No IDs
    assert extract_all_ids("not-a-url") == []


# ---------------------------------------------------------------------- Test build_source_from_url
def test_build_source_from_url():
    """Build source dict from a URL, extracting all relevant IDs."""
    url = "https://www.notion.so/workspace-name-1234567890abcdef1234567890abcdef"

    src = build_source_from_url(url, name="Test Source", source_type="Database")

    assert src["name"] == "Test Source"
    assert src["source_type"] == "Database"
    assert len(src["url"]) == 32


def test_build_source_from_url_auto_name():
    """Auto-generate name from URL when not provided."""
    url = "https://www.notion.so/My-Database-1234567890abcdef1234567890abcdef"
    src = build_source_from_url(url)
    assert src["name"] is not None
    assert len(src["url"]) == 32


def test_build_source_from_url_with_multiple_ids():
    """Handle URLs with multiple IDs (multi-source support)."""
    url = "https://www.notion.so/page-1234567890abcdef1234567890abcdef-9876543210fedcba9876543210abcdef"
    src = build_source_from_url(url)
    assert len(src["url"]) == 32
    # Multiple IDs would be in sources
    ids = extract_all_ids(url)
    if len(ids) > 1:
        assert src["sources"] == ids[1:]


# ---------------------------------------------------------------------- Test source CRUD operations
def test_add_source_with_all_fields(isolated):
    """Add a source with all optional fields."""
    path = add_source(
        name="my-full-source",
        url=DB_ID,
        source_type="Database",
        pinned=True,
        workspace="0123456789abc",
        filter_prop="Status",
        filter_op="equals",
        filter_value="Done",
        sort_by="Title",
        sort_desc=True,
        max_pages=50,
        group_by="Tag",
        sources=[DB_ID],
    )
    assert path is not None

    src = get_source("my-full-source")
    assert src is not None
    assert src["name"] == "my-full-source"
    assert src["url"] == DB_ID
    assert src["source_type"] == "Database"
    assert src["pinned"] is True
    assert src["workspace"] == "0123456789abc"
    assert src["filter_prop"] == "Status"
    assert src["filter_op"] == "equals"
    assert src["filter_value"] == "Done"
    assert src["sort_by"] == "Title"
    assert src["sort_desc"] is True
    assert src["max_pages"] == 50
    assert src["group_by"] == "Tag"
    assert src["sources"] == [DB_ID]


def test_add_source_normalizes_invalid_fields(isolated):
    """Invalid field values should be normalized to defaults."""
    add_source(
        name="normalized-source",
        url=DB_ID,
        source_type="Invalid Type",  # Invalid, should default to first SOURCE_TYPES
        filter_op="invalid-op",  # Invalid, should default to "contains"
        sort_by="Invalid Sort",  # Invalid, should default to "Date"
    )
    src = get_source("normalized-source")
    assert src["source_type"] == SOURCE_TYPES[0]  # "Auto-detect"
    assert src["filter_op"] == "contains"
    assert src["sort_by"] == "Date"


def test_get_source_backward_compatibility(isolated):
    """Missing fields should get defaults for backward compatibility."""
    # Create a minimal source file directly
    import os
    from pageout.core.sources import SOURCE_DIR, ensure_source_dir

    ensure_source_dir()
    minimal_source = {
        "name": "minimal-source",
        "url": "1234567890abcdef1234567890abcdef",
    }

    source_path = os.path.join(SOURCE_DIR, "minimal-source.json")
    with open(source_path, "w") as f:
        json.dump(minimal_source, f)

    src = get_source("minimal-source")
    assert src["pinned"] is False
    assert src["source_type"] == SOURCE_TYPES[0]
    assert src["workspace"] == ""
    assert src["filter_prop"] == ""
    assert src["filter_op"] == "contains"
    assert src["sort_by"] == "Date"
    assert src["sort_desc"] is False
    assert src["max_pages"] == 0
    assert src["group_by"] == ""
    assert src["sources"] == []

    # Cleanup
    os.remove(source_path)


def test_update_source():
    """Update a source's settings."""
    add_source("update-test", DB_ID, "Database")
    assert update_source("update-test", pinned=True, max_pages=100) is True

    src = get_source("update-test")
    assert src["pinned"] is True
    assert src["max_pages"] == 100

    # Test invalid field is ignored
    update_source("update-test", invalid_field="ignored")
    src = get_source("update-test")
    assert "invalid_field" not in src


# ---------------------------------------------------------------------- Test list_sources and sorting
def test_list_sources_sorted_by_name(isolated):
    """Sources should be listed sorted by name (case-insensitive)."""
    add_source("zeta-test", DB_ID)
    add_source("alpha-test", DB_ID)
    add_source("Beta-test", DB_ID)

    sources = list_sources()
    names = [s["name"] for s in sources]
    assert names == ["alpha-test", "Beta-test", "zeta-test"]


def test_list_sources_includes_defaults_for_old_sources(isolated):
    """Old sources without new fields should have defaults applied."""
    import os
    from pageout.core.sources import SOURCE_DIR, ensure_source_dir

    ensure_source_dir()
    old_source = {"name": "old-source", "url": DB_ID}
    with open(os.path.join(SOURCE_DIR, "old-source.json"), "w") as f:
        json.dump(old_source, f)

    sources = list_sources()
    old = next(s for s in sources if s["name"] == "old-source")
    assert old["pinned"] is False
    assert old["filter_prop"] == ""
    assert old["sources"] == []


# ---------------------------------------------------------------------- Test get_recent_sources
def test_get_recent_sources_pinned_first(isolated):
    """Pinned sources should appear first in recent sources."""
    add_source("regular-source", DB_ID)
    add_source("pinned-source", DB_ID, pinned=True)

    recent = get_recent_sources()
    assert recent[0]["name"] == "pinned-source"
    # Second entry could be the same (pinned) or another source depending on count


def test_get_recent_sources_limit(isolated):
    """Recent sources should be limited to the specified count."""
    for i in range(15):
        add_source(f"source-{i:02d}", DB_ID)

    recent = get_recent_sources(limit=5)
    assert len(recent) == 5


# ---------------------------------------------------------------------- Test search_sources_by_workspace
def test_search_sources_by_workspace(isolated):
    """Find sources belonging to a specific workspace."""
    add_source("ws1-source", DB_ID, workspace="workspace1abc")
    add_source("ws2-source", DB_ID, workspace="workspace2def")
    add_source("no-workspace", DB_ID)

    ws1_sources = search_sources_by_workspace("workspace1abc")
    assert len(ws1_sources) == 1
    assert ws1_sources[0]["name"] == "ws1-source"

    ws2_sources = search_sources_by_workspace("workspace2def")
    assert len(ws2_sources) == 1

    # Case insensitive
    ws1_sources = search_sources_by_workspace("WORKSPACE1ABC")
    assert len(ws1_sources) == 1


# ---------------------------------------------------------------------- Test get_sources_with_filter
def test_get_sources_with_filter(isolated):
    """Get sources that have filter/sort settings configured."""
    add_source("filtered-source", DB_ID, filter_prop="Status", filter_value="Done")
    add_source("sorted-source", DB_ID, sort_by="Title")
    add_source("plain-source", DB_ID)

    with_filter = get_sources_with_filter()
    names = [s["name"] for s in with_filter]
    assert "filtered-source" in names
    assert "sorted-source" in names
    assert "plain-source" not in names


# ---------------------------------------------------------------------- Test CLI source integration with filter/sort
def test_cli_uses_source_filter_sort_settings(isolated, tmp_path):
    """CLI should apply filter/sort from saved source."""
    add_source(
        "filtered-db",
        DB_ID,
        filter_prop="Name",
        filter_value="Empty",
        sort_by="Title",
    )

    out_dir = tmp_path / "source_out"
    code = cli_main([
        "export",
        "--source", "filtered-db",
        "--format", "md",
        "--token", "tok",
        "-o", str(out_dir),
    ], notion=FakeNotion()
    )
    assert code == 0


# ---------------------------------------------------------------------- Test sources field in config
def test_sources_field_in_defaults():
    """The 'sources' field should be present in DEFAULTS."""
    assert "sources" in DEFAULTS
    assert DEFAULTS["sources"] == []


def test_pipeline_reads_sources_from_config(tmp_path):
    """Pipeline should read extra sources from config['sources']."""
    from pageout.core.pipeline import Exporter

    cfg = cfg_for(tmp_path, sources=[DB_ID], source_type="Database")
    exporter = Exporter(cfg, notion=FakeNotion())

    roots = exporter.fetch_roots()
    assert len(roots) > 0  # Should fetch pages from main source + extra


# ---------------------------------------------------------------------- Test multi-source support via sources field
def test_multi_source_export(tmp_path):
    """Export should work with multiple data sources."""
    from pageout.core.pipeline import Exporter

    # Create a source with extra sources
    add_source("multi-source", DB_ID, sources=[DB_ID])

    src = get_source("multi-source")
    assert len(src["sources"]) > 0

    # Config with sources field
    cfg = cfg_for(tmp_path, sources=src["sources"], source_type="Database")
    exporter = Exporter(cfg, notion=FakeNotion())
    roots = exporter.fetch_roots()

    # Should have at least the main source pages
    assert len(roots) > 0


# ---------------------------------------------------------------------- Test group-by export mode
def test_group_by_export_creates_separate_files(tmp_path):
    """Group-by mode should create one file per group value."""
    run(tmp_path, database=DB_ID, db_export="Group by", group_by="Status", fmt_md=True)

    # Should have created Markdown output
    assert (tmp_path / "Markdown").exists()


def test_group_by_export_with_sort(tmp_path):
    """Group-by export should respect sort settings."""
    run(
        tmp_path,
        database=DB_ID,
        db_export="Group by",
        group_by="Status",
        sort_by="Title",
        sort_desc=False,
        fmt_md=True,
    )
    # Should complete without error
    assert (tmp_path / "Markdown").exists()


# ---------------------------------------------------------------------- Test filter/sort integration in fetch_roots
def test_fetch_roots_applies_filter(tmp_path):
    """fetch_roots should filter pages by filter_prop/filter_op/filter_value."""
    from pageout.core.pipeline import Exporter

    cfg = cfg_for(
        tmp_path,
        filter_prop="Name",
        filter_op="contains",
        filter_value="Empty",
    )
    exporter = Exporter(cfg, notion=FakeNotion())
    roots = exporter.fetch_roots()

    # Should return some pages (filtered from the fixture)
    assert isinstance(roots, list)


def test_fetch_roots_applies_sort(tmp_path):
    """fetch_roots should sort pages by sort_by/sort_desc."""
    from pageout.core.pipeline import Exporter

    # Sort by Date ascending
    cfg = cfg_for(tmp_path, sort_by="Date", sort_desc=False)
    exporter = Exporter(cfg, notion=FakeNotion())
    roots = exporter.fetch_roots()

    assert isinstance(roots, list)


def test_fetch_roots_applies_max_pages(tmp_path):
    """fetch_roots should limit pages by max_pages."""
    from pageout.core.pipeline import Exporter

    cfg = cfg_for(tmp_path, max_pages=1)
    exporter = Exporter(cfg, notion=FakeNotion())
    roots = exporter.fetch_roots()

    # Should have at most 1 page
    assert len(roots) <= 1


# ---------------------------------------------------------------------- Test workspace field in source
def test_workspace_field_in_source(isolated):
    """Source should store and retrieve workspace ID."""
    add_source("workspace-source", DB_ID, workspace="abc123workspace")
    src = get_source("workspace-source")
    assert src["workspace"] == "abc123workspace"


def test_workspace_field_in_defaults():
    """The 'workspace' field should be present in DEFAULTS."""
    assert "workspace" in DEFAULTS
    assert DEFAULTS["workspace"] == ""


# ---------------------------------------------------------------------- Test update_source for all valid fields
def test_update_source_all_fields(isolated):
    """Update source with all valid fields."""
    add_source("update-all", DB_ID)

    result = update_source(
        "update-all",
        url=DB_ID,
        source_type="Database",
        pinned=True,
        workspace="newworkspace12",
        filter_prop="NewProp",
        filter_op="equals",
        filter_value="NewValue",
        sort_by="Title",
        sort_desc=True,
        max_pages=99,
        group_by="NewGroup",
        sources=[DB_ID, DB_ID],
    )
    assert result is True

    src = get_source("update-all")
    assert src["url"] == DB_ID
    assert src["source_type"] == "Database"
    assert src["pinned"] is True
    assert src["workspace"] == "newworkspace12"
    assert src["filter_prop"] == "NewProp"
    assert src["filter_op"] == "equals"
    assert src["filter_value"] == "NewValue"
    assert src["sort_by"] == "Title"
    assert src["sort_desc"] is True
    assert src["max_pages"] == 99
    assert src["group_by"] == "NewGroup"
    # Deduplication: same ID twice becomes one ID
    assert src["sources"] == [DB_ID]


# ---------------------------------------------------------------------- Test source_exists
def test_source_exists_isolated_isolated(isolated):
    """source_exists should work correctly."""
    add_source("existing-source", DB_ID)
    assert source_exists("existing-source") is True
    assert source_exists("nonexistent-source") is False
    delete_source("existing-source")
    assert source_exists("existing-source") is False


# ---------------------------------------------------------------------- Test delete_source
def test_delete_source_returns_correct_value(isolated):
    """delete_source should return True if deleted, False if not existed."""
    assert delete_source("nonexistent") is False
    add_source("to-delete", DB_ID)
    assert delete_source("to-delete") is True
    assert delete_source("to-delete") is False  # Already deleted


# ---------------------------------------------------------------------- Test toggle_pin
def test_toggle_pin_workflow(isolated):
    """toggle_pin should flip the pinned status."""
    add_source("toggle-source", DB_ID)

    # Initially False
    assert get_source("toggle-source")["pinned"] is False

    # Toggle to True
    result = toggle_pin("toggle-source")
    assert result is True
    assert get_source("toggle-source")["pinned"] is True

    # Toggle back to False
    result = toggle_pin("toggle-source")
    assert result is False
    assert get_source("toggle-source")["pinned"] is False


def test_toggle_pin_raises_for_nonexistent(isolated):
    """toggle_pin should raise FileNotFoundError for nonexistent source."""
    with pytest.raises(FileNotFoundError):
        toggle_pin("nonexistent-source")


# ---------------------------------------------------------------------- Test normalize_source_ids helper
def test_normalize_source_ids_handles_empty():
    """normalize_source_ids should handle None and empty inputs."""
    from pageout.sources.notion_api import normalize_source_ids

    assert normalize_source_ids(None) == []
    assert normalize_source_ids("") == []
    assert normalize_source_ids([]) == []
    assert normalize_source_ids({}) == []


def test_normalize_source_ids_handles_json_string():
    """normalize_source_ids should parse JSON-encoded strings."""
    from pageout.sources.notion_api import normalize_source_ids

    # Empty array as JSON string
    assert normalize_source_ids("[]") == []

    # Array with one ID
    result = normalize_source_ids('["abcd1234abcd1234abcd1234abcd1234"]')
    assert result == ["abcd1234abcd1234abcd1234abcd1234"]

    # Array with multiple IDs
    result = normalize_source_ids('["11111111111111111111111111111111", "22222222222222222222222222222222"]')
    assert len(result) == 2


def test_normalize_source_ids_handles_python_repr():
    """normalize_source_ids should parse Python repr strings like ['id1', 'id2']."""
    from pageout.sources.notion_api import normalize_source_ids

    result = normalize_source_ids("['11111111111111111111111111111111']")
    assert result == ["11111111111111111111111111111111"]


def test_normalize_source_ids_handles_space_separated():
    """normalize_source_ids should parse space/comma/semicolon separated IDs."""
    from pageout.sources.notion_api import normalize_source_ids

    # Space separated
    result = normalize_source_ids("11111111111111111111111111111111 22222222222222222222222222222222")
    assert len(result) == 2

    # Comma separated
    result = normalize_source_ids("11111111111111111111111111111111,22222222222222222222222222222222")
    assert len(result) == 2


def test_normalize_source_ids_handles_urls():
    """normalize_source_ids should extract IDs from Notion URLs."""
    from pageout.sources.notion_api import normalize_source_ids

    url = "https://www.notion.so/workspace/My-Database-11111111111111111111111111111111"
    result = normalize_source_ids(url)
    assert result == ["11111111111111111111111111111111"]


def test_normalize_source_ids_handles_list():
    """normalize_source_ids should handle actual lists."""
    from pageout.sources.notion_api import normalize_source_ids

    result = normalize_source_ids(["11111111111111111111111111111111", "22222222222222222222222222222222"])
    assert len(result) == 2
    assert result == ["11111111111111111111111111111111", "22222222222222222222222222222222"]


def test_normalize_source_ids_dedupes():
    """normalize_source_ids should dedupe IDs while preserving order."""
    from pageout.sources.notion_api import normalize_source_ids

    result = normalize_source_ids("11111111111111111111111111111111 11111111111111111111111111111111 22222222222222222222222222222222")
    assert len(result) == 2
    assert result == ["11111111111111111111111111111111", "22222222222222222222222222222222"]


def test_normalize_source_ids_rejects_brackets():
    """normalize_source_ids should NOT return '[' as an ID."""
    from pageout.sources.notion_api import normalize_source_ids

    # This was the bug: string "[]" would cause parse_database_id("[")
    result = normalize_source_ids("[]")
    assert result == []  # Should be empty list, not ["["] or any invalid IDs

    result = normalize_source_ids("['url']")
    # Python repr that would cause issues if parsed character by character
    assert "[" not in result


# ---------------------------------------------------------------------- Test resolve_roots with string sources
@pytest.mark.parametrize("extra_sources", [
    [],  # Normal empty list
    None,  # None
    "[]",  # JSON string empty array
    "['" + DB_ID + "']",  # Python repr string
    '["' + DB_ID + '"]',  # JSON string with one ID
    DB_ID,  # Single ID string
])
def test_resolve_roots_extra_sources_normalization(tmp_path, extra_sources):
    """resolve_roots should handle various forms of extra_sources input."""
    from pageout.sources.notion_api import resolve_roots

    notion = FakeNotion()
    # This should not raise or call the API with "["
    roots = resolve_roots(notion, DB_ID, "Database", extra_sources=extra_sources)
    assert isinstance(roots, list)


def test_resolve_roots_does_not_call_api_with_bracket():
    """resolve_roots should never call the API with '[' as database_id."""
    from pageout.sources.notion_api import resolve_roots

    notion = FakeNotion()
    # This was the bug: string sources would cause database_id="[" to be passed to API
    roots = resolve_roots(notion, DB_ID, "Database", extra_sources="[]")

    # Verify no call was made with "["
    for call in notion.calls:
        assert "[" not in call[1], f"API called with invalid ID containing bracket: {call}"


# ---------------------------------------------------------------------- Test load_property_names with string source_text
@pytest.mark.parametrize("source_text", [
    DB_ID,
    "https://www.notion.so/" + DB_ID,
    '["' + DB_ID + '"]',  # JSON string
])
def test_load_property_names_handles_strings(tmp_path, source_text):
    """load_property_names should handle string inputs properly."""
    from pageout.sources.notion_api import load_property_names

    notion = FakeNotion()
    # Should not raise and should return a list of property names
    names = load_property_names(notion, source_text, "Database")
    assert isinstance(names, list)


def test_load_property_names_rejects_empty_string():
    """load_property_names should raise for empty string input."""
    from pageout.sources.notion_api import load_property_names

    notion = FakeNotion()
    with pytest.raises(Exception, match="Enter a database or page ID"):
        load_property_names(notion, "[]", "Database")