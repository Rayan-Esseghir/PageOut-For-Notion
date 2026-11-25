"""PDF helpers that do not need Chromium (printing itself is covered by the manual checklist)."""

import io

import pytest

import pageout.core.config as config
from pageout.renderers import pdf


def test_pdf_kwargs_margins_and_page_numbers():
    cfg = dict(config.DEFAULTS, margin_mm=20, page_numbers=False)
    kw = pdf.pdf_kwargs(cfg, "x.pdf")
    assert kw["margin"] == {"top": "20mm", "bottom": "20mm", "left": "20mm", "right": "20mm"}
    assert kw["format"] == "A4" and kw["landscape"] is False and "display_header_footer" not in kw
    cfg.update(page_numbers=True, page_num_position="Top Right", margin_mm=5, orientation="Landscape", scale=150)
    kw = pdf.pdf_kwargs(cfg, "x.pdf")
    assert kw["display_header_footer"] and kw["margin"]["top"] == "15mm" and kw["margin"]["bottom"] == "5mm"
    assert kw["landscape"] is True and kw["scale"] == 1.5
    assert "pageNumber" in kw["header_template"] and kw["footer_template"] == "<span></span>"


@pytest.mark.parametrize("pos,align", [("Bottom Center", "center"), ("Bottom Right", "right")])
def test_pagenum_templates(pos, align):
    hdr, ftr = pdf._pagenum_templates(dict(page_num_position=pos, page_num_format="Page X of Y"))
    assert hdr == "<span></span>" and f"text-align:{align}" in ftr and "totalPages" in ftr


def test_remove_blank_pages(tmp_path):
    PIL = pytest.importorskip("PIL.Image")
    pypdf = pytest.importorskip("pypdf")
    buf = io.BytesIO()
    PIL.new("RGB", (40, 40), (200, 10, 10)).save(buf, "PDF")
    content = pypdf.PdfReader(io.BytesIO(buf.getvalue())).pages[0]
    w = pypdf.PdfWriter()
    w.add_page(content)
    w.add_blank_page(width=200, height=200)
    w.add_page(content)
    w.add_blank_page(width=200, height=200)
    path = tmp_path / "t.pdf"
    with open(path, "wb") as f:
        w.write(f)
    assert pdf.remove_blank_pages(str(path)) == 2
    assert len(pypdf.PdfReader(str(path)).pages) == 2
    assert pdf.remove_blank_pages(str(path)) == 0  # nothing left to remove


def test_link_js_and_hide_props_are_strings():
    assert "notion" in pdf.LINKS_JS and "aria-expanded" in pdf.EXPAND_JS
