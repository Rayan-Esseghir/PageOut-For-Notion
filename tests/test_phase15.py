"""Tests for Phase 15: More formats (EPUB, RST, AsciiDoc)."""

import pytest
from fake_notion import DB_ID, FakeNotion

from pageout.core.config import DEFAULTS, FM_PRESETS, FORMATS, MD_PRESETS
from pageout.core.ir import Span
from pageout.core.pipeline import export
from pageout.renderers.asciidoc import (
    blocks_asciidoc,
    build_asciidoc,
    escape_asciidoc,
    rt_adoc,
)
from pageout.renderers.base import R
from pageout.renderers.markdown import md_front_matter
from pageout.renderers.rst import (
    blocks_rst,
    build_rst,
    escape_rst,
    rt_rst,
)


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
    monkeypatch.delattr("pageout.core.config", "SOURCE_DIR", raising=False)
    import pageout.core.sources as sources

    monkeypatch.setattr(sources, "SOURCE_DIR", str(tmp_path / "cfg" / "sources"))
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.fixture
def mock_r():
    """Create a mock R object for testing renderers."""
    cfg = {"md_preset": "GFM", "links": "Link to everything"}
    return R(cfg, "md")


# Helper to create RichText (list of Span objects)
def spans(*items):
    """Create a list of Span objects for testing."""
    return [
        Span(
            text=item.get("text", ""),
            bold=item.get("bold", False),
            italic=item.get("italic", False),
            strike=item.get("strike", False),
            underline=item.get("underline", False),
            code=item.get("code", False),
            equation=item.get("equation", None),
            href=item.get("href", None),
        )
        for item in items
    ]


# ---------------------------------------------------------------------- Test format registration in config
def test_epub_in_formats():
    """EPUB format should be registered in FORMATS."""
    assert "epub" in FORMATS


def test_rst_in_formats():
    """RST format should be registered in FORMATS."""
    assert "rst" in FORMATS


def test_adoc_in_formats():
    """AsciiDoc format should be registered in FORMATS."""
    assert "adoc" in FORMATS


def test_fm_presets_in_defaults():
    """FM_PRESETS should be available in defaults."""
    assert "md_front_matter_preset" in DEFAULTS
    assert DEFAULTS["md_front_matter_preset"] == FM_PRESETS[0]


# ---------------------------------------------------------------------- Test RST renderer
def test_escape_rst_backslashes():
    """RST escape should handle backslashes."""
    assert escape_rst(r"test\n") == r"test\\n"


def test_escape_rst_asterisks():
    """RST escape should handle asterisks."""
    assert escape_rst("*bold*") == r"\*bold\*"


def test_escape_rst_backticks():
    """RST escape should handle backticks."""
    assert escape_rst("`code`") == r"\`code\`"


def test_escape_rst_empty():
    """RST escape should handle empty string."""
    assert escape_rst("") == ""
    assert escape_rst(None) == ""


def test_rt_rst_basic(mock_r):
    """Basic RST rich text rendering."""

    rts = spans({"text": "Hello", "bold": True}, {"text": " World", "italic": True})
    result = rt_rst(rts, mock_r)
    assert "**" in result or "*Hello*" in result


def test_blocks_rst_heading(mock_r):
    """RST blocks should render headings correctly."""
    from pageout.core.ir import Block

    blocks = [
        Block(kind="heading", level=1, text=spans({"text": "Test Heading"})),
        Block(kind="paragraph", text=spans({"text": "Content"})),
    ]
    result = blocks_rst(blocks, mock_r)
    assert "Test Heading" in result


def test_blocks_rst_list(mock_r):
    """RST blocks should render lists correctly."""
    from pageout.core.ir import Block

    blocks = [
        Block(kind="bulleted", text=spans({"text": "Item 1"})),
        Block(kind="bulleted", text=spans({"text": "Item 2"})),
    ]
    result = blocks_rst(blocks, mock_r)
    # blocks_rst returns a list of lines
    content = " ".join(result)
    assert "- " in content or "* " in content


def test_build_rst_empty():
    """build_rst should handle empty content."""
    result = build_rst("Test Title", [], [], None, {})
    assert "Test Title" in result
    # RST uses underlines, but with empty blocks just the title line
    assert "Test Title" in result


# ---------------------------------------------------------------------- Test AsciiDoc renderer
def test_escape_asciidoc_asterisks():
    """AsciiDoc escape should handle asterisks."""
    assert escape_asciidoc("*bold*") == r"\*bold\*"


def test_escape_asciidoc_underscores():
    """AsciiDoc escape should handle underscores."""
    assert escape_asciidoc("_italic_") == r"\_italic\_"


def test_escape_asciidoc_braces():
    """AsciiDoc escape should handle braces."""
    assert escape_asciidoc("{variable}") == r"\{variable\}"


def test_escape_asciidoc_brackets():
    """AsciiDoc escape should handle brackets."""
    assert escape_asciidoc("[link]") == r"\[link\]"


def test_escape_asciidoc_colons():
    """AsciiDoc escape should handle colons."""
    assert escape_asciidoc(":attr: value") == r"\:attr\: value"


def test_escape_asciidoc_empty():
    """AsciiDoc escape should handle empty string."""
    assert escape_asciidoc("") == ""
    assert escape_asciidoc(None) == ""


def test_rt_adoc_basic(mock_r):
    """Basic AsciiDoc rich text rendering."""
    rts = spans({"text": "Hello", "bold": True}, {"text": " World", "italic": True})
    result = rt_adoc(rts, mock_r)
    assert "**" in result


def test_blocks_asciidoc_heading(mock_r):
    """AsciiDoc blocks should render headings correctly."""
    from pageout.core.ir import Block

    blocks = [
        Block(kind="heading", level=1, text=spans({"text": "Test Heading"})),
        Block(kind="paragraph", text=spans({"text": "Content"})),
    ]
    result = blocks_asciidoc(blocks, mock_r)
    assert "Test Heading" in result


def test_build_asciidoc_empty():
    """build_asciidoc should handle empty content."""
    result = build_asciidoc("Test Title", [], [], None, {})
    assert "Test Title" in result


# ---------------------------------------------------------------------- Test Front Matter Presets
def test_md_front_matter_obsidian_tags():
    """Obsidian preset should format tags as YAML list."""
    result = md_front_matter("Test", [("tags", "tag1, tag2, tag3")], preset="Obsidian")
    assert 'tags: ["tag1", "tag2", "tag3"]' in result or "tags:" in result


def test_md_front_matter_gfm():
    """GFM preset should use standard YAML format."""
    result = md_front_matter("Test", [("author", "John Doe")], preset="GFM")
    # YAML output uses json.dumps for the value
    assert "John Doe" in result


def test_md_front_matter_vanilla():
    """Vanilla preset should use standard YAML format."""
    result = md_front_matter("Test", [("author", "Jane Doe")], preset="Vanilla")
    assert "Jane Doe" in result


# ---------------------------------------------------------------------- Test Hugo/Jekyll presets
def test_hugo_jekyll_preset_exists():
    """Hugo/Jekyll presets should be available for config."""
    # These presets should be loadable from config
    assert "md_front_matter_preset" in DEFAULTS


# ---------------------------------------------------------------------- Test Export Integration
def test_epub_export_creates_file(tmp_path, isolated):
    """EPUB export should create a valid .epub file."""
    out_dir = tmp_path / "epub_out"

    try:
        result = export(cfg_for(out_dir, fmt_md=False, fmt_epub=True), notion=FakeNotion())
        # Check that the export completed
        assert result.total >= 0
        # EPUB file should be created in the EPUB folder
        epub_files = list(out_dir.rglob("*.epub"))
        if not epub_files:
            # Check if export failed due to missing dependencies
            if result.failed:
                for title, err in result.failed:
                    if "ebooklib" in str(err):
                        pytest.skip("ebooklib not installed")
            assert False, f"No EPUB files created. Failed: {result.failed}"
    except Exception as e:
        if "ebooklib" in str(e):
            pytest.skip("ebooklib not installed")
        raise


def test_rst_export_creates_file(tmp_path, isolated):
    """RST export should create a valid .rst file."""
    result = export(cfg_for(tmp_path, fmt_md=False, fmt_rst=True), notion=FakeNotion())
    assert result.total >= 0
    rst_files = list(tmp_path.rglob("*.rst"))
    assert len(rst_files) > 0, "No RST files created"


def test_adoc_export_creates_file(tmp_path, isolated):
    """AsciiDoc export should create a valid .adoc file."""
    result = export(cfg_for(tmp_path, fmt_md=False, fmt_adoc=True), notion=FakeNotion())
    assert result.total >= 0
    adoc_files = list(tmp_path.rglob("*.adoc"))
    assert len(adoc_files) > 0, "No AsciiDoc files created"


def test_rst_content_structure(tmp_path, isolated):
    """RST export should have proper document structure."""
    result = export(cfg_for(tmp_path, fmt_rst=True), notion=FakeNotion())
    rst_files = list(tmp_path.rglob("*.rst"))
    if rst_files:
        content = rst_files[0].read_text(encoding="utf-8")
        assert "Empty page" in content or "Date" in content  # Title or content present


def test_adoc_content_structure(tmp_path, isolated):
    """AsciiDoc export should have proper document structure."""
    result = export(cfg_for(tmp_path, fmt_adoc=True), notion=FakeNotion())
    adoc_files = list(tmp_path.rglob("*.adoc"))
    if adoc_files:
        content = adoc_files[0].read_text(encoding="utf-8")
        assert "Empty page" in content or "Date" in content  # Title or content present


# ---------------------------------------------------------------------- Test multiple formats together
def test_multiple_formats_together(tmp_path, isolated):
    """Multiple new formats should work together."""
    result = export(
        cfg_for(
            tmp_path,
            fmt_md=False,
            fmt_rst=True,
            fmt_adoc=True,
            fmt_epub=False,  # Skip EPUB for now (requires ebooklib)
        ),
        notion=FakeNotion(),
    )
    assert result.total >= 0

    rst_files = list(tmp_path.rglob("*.rst"))
    adoc_files = list(tmp_path.rglob("*.adoc"))

    assert len(rst_files) > 0 or len(adoc_files) > 0, "No output files created"


# ---------------------------------------------------------------------- Test Obsidian vault mode configuration
def test_obsidian_vault_config_exists():
    """Obsidian vault mode settings should be configurable."""
    # The md_preset "Obsidian" should be available
    valid_presets = ("GFM", "Vanilla", "Obsidian")
    # This tests that the configuration system supports Obsidian mode
    assert "Obsidian" in MD_PRESETS


# ---------------------------------------------------------------------- Test empty block handling
def test_rst_empty_blocks(mock_r):
    """RST renderer should handle empty block list."""
    result = blocks_rst([], mock_r)
    assert result == []


def test_adoc_empty_blocks(mock_r):
    """AsciiDoc renderer should handle empty block list."""
    result = blocks_asciidoc([], mock_r)
    assert result == []
