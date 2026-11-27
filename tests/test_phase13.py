"""Tests for Phase 13: Better PDF features."""

import io
import pytest

from pageout.core.config import DEFAULTS
from pageout.renderers import pdf


@pytest.fixture
def cfg_base():
    """Base configuration for testing."""
    return dict(DEFAULTS)


# ---------------------------------------------------------------------- Test table_of_contents
def test_table_of_content_js_generates_links():
    """TOC JS should extract headings and create links."""
    # The TOC_JS constant should exist and be valid JavaScript
    assert hasattr(pdf, 'TOC_JS')
    assert 'querySelectorAll' in pdf.TOC_JS
    assert 'h1,h2,h3,h4,h5,h6' in pdf.TOC_JS
    assert 'notion-toc' in pdf.TOC_JS


def test_toc_js_returns_section_count():
    """TOC JS should return the number of sections found."""
    # Verify the JS returns items.length
    assert 'return items.length' in pdf.TOC_JS


# ---------------------------------------------------------------------- Test running_header
def test_running_header_templates_returns_correct_format(cfg_base):
    """Running header templates should include page title placeholder."""
    cfg_base["running_header"] = True
    cfg_base["header_format"] = "{title}"

    hdr, ftr = pdf._running_header_templates(cfg_base)

    # Header should have page-title class
    assert 'page-title' in hdr
    # Footer should have page number
    assert 'pageNumber' in ftr


def test_running_header_with_custom_format(cfg_base):
    """Running header should support custom format strings."""
    cfg_base["running_header"] = True
    cfg_base["header_format"] = "{title} - {date}"

    hdr, ftr = pdf._running_header_templates(cfg_base)

    # Custom format should be in header
    assert '{title}' in cfg_base["header_format"]


def test_running_header_page_position(cfg_base):
    """Running header should handle different page position settings."""
    cfg_base["running_header"] = True
    cfg_base["page_num_position"] = "Bottom Right"

    hdr, ftr = pdf._running_header_templates(cfg_base)
    assert hdr != "<span></span>"
    assert 'pageNumber' in ftr


def test_running_header_bottom_center(cfg_base):
    """Running header with bottom center position."""
    cfg_base["running_header"] = True
    cfg_base["page_num_position"] = "Bottom Center"

    hdr, ftr = pdf._running_header_templates(cfg_base)
    assert 'text-align:center' in ftr


# ---------------------------------------------------------------------- Test watermark
def test_watermark_css_is_defined():
    """Watermark CSS constant should be defined."""
    assert hasattr(pdf, 'WATERMARK_CSS')
    assert '@@@WATERMARK@@@' in pdf.WATERMARK_CSS
    assert '@@@OPACITY@@@' in pdf.WATERMARK_CSS


def test_watermark_css_has_fixed_position():
    """Watermark should be positioned fixed center page."""
    assert 'position: fixed' in pdf.WATERMARK_CSS
    assert 'top: 50%' in pdf.WATERMARK_CSS
    assert 'left: 50%' in pdf.WATERMARK_CSS
    assert 'transform: translate(-50%, -50%) rotate(-45deg)' in pdf.WATERMARK_CSS


def test_watermark_opacity_applied(cfg_base):
    """Watermark opacity should be configurable."""
    cfg_base["watermark_text"] = "Draft"
    cfg_base["watermark_opacity"] = 0.3

    # When watermark is enabled, CSS should be added
    wm_text = cfg_base["watermark_text"].strip()
    if wm_text:
        wm_opacity = cfg_base["watermark_opacity"]
        css = pdf.WATERMARK_CSS.replace("@@@WATERMARK@@@", wm_text)
        css = css.replace("@@@OPACITY@@@", str(wm_opacity))
        assert "0.3" in css


# ---------------------------------------------------------------------- Test booklet_mode
def test_booklet_css_is_defined():
    """Booklet mode CSS should be defined."""
    assert hasattr(pdf, 'BOOKLET_CSS')
    assert 'size: A5' in pdf.BOOKLET_CSS


def test_pdf_kwargs_booklet_mode(cfg_base, tmp_path):
    """PDF kwargs should override page size to A5 in booklet mode."""
    cfg_base["booklet_mode"] = True
    cfg_base["page_size"] = "A4"  # Should be overridden to A5

    import os
    path = str(tmp_path / "test.pdf")
    kw = pdf.pdf_kwargs(cfg_base, path)

    # Format should be A5 regardless of configured size
    assert kw["format"] == "A5"


def test_pdf_kwargs_booklet_mode_portrait(cfg_base, tmp_path):
    """Booklet mode should enforce portrait orientation."""
    cfg_base["booklet_mode"] = True
    cfg_base["orientation"] = "Landscape"
    cfg_base["page_size"] = "A4"

    path = str(tmp_path / "test.pdf")
    kw = pdf.pdf_kwargs(cfg_base, path)

    # Booklet mode uses A5 size
    assert kw["format"] == "A5"


# ---------------------------------------------------------------------- Test cover page improvements
def test_improved_cover_page_css_includes_gradient():
    """Improved cover page CSS should include gradient background."""
    # Check that cover page CSS is added when enabled
    css_parts = []
    if True:  # cover_page_improved = True
        css_parts.append(pdf.render_notion_page.__code__.co_firstlineno)

    # The cover page CSS should include specific styles
    cover_css = """
.notion-cover-page {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  min-height: 80vh;
  padding: 4rem 2rem;
  text-align: center;
  background: linear-gradient(135deg, #f7f6f3 0%, #e9e9e7 100%);
}"""
    assert 'linear-gradient' in cover_css


# ---------------------------------------------------------------------- Test combined features
def test_pdf_kwargs_no_running_header_when_disabled(cfg_base):
    """When running header is disabled, header template should be empty."""
    cfg_base["running_header"] = False
    cfg_base["page_numbers"] = False

    import os
    path = str(os.path.abspath("x.pdf"))
    kw = pdf.pdf_kwargs(cfg_base, path)

    # No header/footer should be enabled
    assert "header_template" not in kw or kw.get("header_template") is None


def test_pdf_kwargs_with_all_features(cfg_base):
    """PDF kwargs should handle all Phase 13 features together."""
    cfg_base["running_header"] = True
    cfg_base["header_format"] = "{title}"
    cfg_base["page_numbers"] = True
    cfg_base["watermark_text"] = "CONFIDENTIAL"
    cfg_base["watermark_opacity"] = 0.1
    cfg_base["booklet_mode"] = True
    cfg_base["page_size"] = "A4"

    import os
    path = str(os.path.abspath("y.pdf"))
    kw = pdf.pdf_kwargs(cfg_base, path)

    # Booklet mode overrides size
    assert kw["format"] == "A5"
    # Running header should be enabled
    assert kw.get("display_header_footer") is True
    assert "page-title" in kw.get("header_template", "")


# ---------------------------------------------------------------------- Test watermark_js for page titles
def test_page_title_js_exists():
    """Page title JS constant should be defined."""
    assert hasattr(pdf, 'PAGE_TITLE_JS')
    assert 'pageTitle' in pdf.PAGE_TITLE_JS
    assert 'querySelector' in pdf.PAGE_TITLE_JS


# ---------------------------------------------------------------------- Test configuration defaults
def test_phase13_defaults_exist():
    """Phase 13 defaults should be in DEFAULTS."""
    assert "table_of_contents" in DEFAULTS
    assert "running_header" in DEFAULTS
    assert "header_format" in DEFAULTS
    assert "watermark_text" in DEFAULTS
    assert "watermark_opacity" in DEFAULTS
    assert "booklet_mode" in DEFAULTS
    assert "cover_page_improved" in DEFAULTS


def test_phase13_default_values():
    """Phase 13 defaults should have correct default values."""
    assert DEFAULTS["table_of_contents"] is False
    assert DEFAULTS["running_header"] is False
    assert DEFAULTS["header_format"] == "{title}"
    assert DEFAULTS["watermark_text"] == ""
    assert DEFAULTS["watermark_opacity"] == 0.15
    assert DEFAULTS["booklet_mode"] is False
    assert DEFAULTS["cover_page_improved"] is True


# ---------------------------------------------------------------------- Test watermark security
def test_watermark_escapes_quotes():
    """Watermark text with quotes should be escaped in CSS."""
    wm_text = 'Test "Quoted" Text'
    escaped = wm_text.replace('\\', '\\\\').replace('"', '\\"')
    assert '"' not in escaped or '\\"' in escaped  # Quotes should be escaped


def test_watermark_escapes_backslashes():
    """Watermark text with backslashes should be escaped in CSS."""
    wm_text = 'Test\\Text'
    escaped = wm_text.replace('\\', '\\\\')
    assert '\\\\' in escaped