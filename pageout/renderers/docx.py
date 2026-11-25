"""Word (.docx) renderer."""

import io

from pageout.core.config import ICON_MODES
from pageout.core.ir import plain_text
from pageout.renderers.html import _build_caption


def build_docx(title, icon_text, rows, tree, r, path, cfg):
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Inches, Pt, RGBColor
    except ImportError:
        raise Exception("Word export needs: pip install python-docx")

    doc = Document()

    # Page icon (emoji only for Word)
    icon_mode = cfg.get("icon_mode", ICON_MODES[0])
    if icon_mode != "Hide icon" and icon_text:
        p = doc.add_paragraph()
        p.add_run(icon_text).font.size = Pt(28)

    # Title
    heading = doc.add_heading(title, 0)
    if cfg.get("heading_align") == "Center":
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Title separator
    if cfg.get("title_separator"):
        p = doc.add_paragraph()
        p.add_run("─" * 40).font.color.rgb = RGBColor(0xE3, 0xE2, 0xE0)

    # Properties
    prop_layout = cfg.get("prop_layout", "Notion Table")
    if rows and prop_layout != "Hidden":
        if prop_layout in ("Notion Table", "Minimalist List"):
            tb = doc.add_table(rows=0, cols=2)
            tb.style = "Table Grid"
            for k, v in rows:
                cells = tb.add_row().cells
                cells[0].text = k
                cells[1].text = v
                cells[0].paragraphs[0].runs[0].font.color.rgb = RGBColor(0x78, 0x77, 0x74)
        elif prop_layout == "Inline Pills":
            p = doc.add_paragraph()
            for i, (k, v) in enumerate(rows):
                if i:
                    p.add_run("  ")
                run = p.add_run(f"{k}: {v}")
                run.font.size = Pt(9)
        doc.add_paragraph()

    # Cover page break
    if cfg.get("cover_page"):
        from docx.oxml import OxmlElement as _OE
        from docx.oxml.ns import qn as _qn

        p = doc.add_paragraph()
        pPr = p._p.get_or_add_pPr()
        pb = _OE("w:pageBreakBefore")
        pb.set(_qn("w:val"), "true")
        pPr.append(pb)

    def hyperlink(par, text, url):
        rid = par.part.relate_to(
            url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink", is_external=True
        )
        h = OxmlElement("w:hyperlink")
        h.set(qn("r:id"), rid)
        run = OxmlElement("w:r")
        rpr = OxmlElement("w:rPr")
        u = OxmlElement("w:u")
        u.set(qn("w:val"), "single")
        col = OxmlElement("w:color")
        col.set(qn("w:val"), "0563C1")
        rpr.append(u)
        rpr.append(col)
        run.append(rpr)
        tx = OxmlElement("w:t")
        tx.text = text
        run.append(tx)
        h.append(run)
        par._p.append(h)

    def runs(par, rts):
        for x in rts or []:
            txt = x.text
            if not txt:
                continue
            href = r.href_for(x)
            if href and href.startswith(("http://", "https://", "mailto:")):
                hyperlink(par, txt, href)
                continue
            run = par.add_run(txt)
            run.bold = True if x.bold else None
            run.italic = True if x.italic else None
            run.underline = True if x.underline else None
            run.font.strike = True if x.strike else None
            if x.code:
                run.font.name = "Consolas"

    def do_indent(par, depth):
        if depth:
            par.paragraph_format.left_indent = Inches(0.3 * depth)

    img_num = [0]

    def add(blocks, depth=0):
        for b in blocks:
            t = b.kind
            kids = b.children
            lvl = min(depth + 1, 3)
            if t == "paragraph":
                p = doc.add_paragraph()
                runs(p, b.text)
                do_indent(p, depth)
            elif t == "heading":
                p = doc.add_heading(level=b.level)
                runs(p, b.text)
                if cfg.get("heading_align") == "Center":
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            elif t == "bulleted":
                p = doc.add_paragraph(style="List Bullet" if lvl == 1 else f"List Bullet {lvl}")
                runs(p, b.text)
            elif t == "numbered":
                p = doc.add_paragraph(style="List Number" if lvl == 1 else f"List Number {lvl}")
                runs(p, b.text)
            elif t == "todo":
                p = doc.add_paragraph("☑ " if b.checked else "☐ ")
                runs(p, b.text)
                do_indent(p, depth)
            elif t in ("quote", "callout"):
                p = doc.add_paragraph(style="Quote")
                if t == "callout" and b.icon:
                    p.add_run(b.icon + " ")
                runs(p, b.text)
            elif t == "toggle":
                p = doc.add_paragraph()
                runs(p, b.text)
                for run in p.runs:
                    run.bold = True
                do_indent(p, depth)
            elif t == "code":
                p = doc.add_paragraph()
                run = p.add_run(plain_text(b.text))
                run.font.name = "Consolas"
                do_indent(p, depth)
            elif t == "divider":
                doc.add_paragraph("─" * 20)
            elif t == "equation":
                doc.add_paragraph(b.expression)
            elif t == "image":
                m = b.media
                img = m.asset if m else None
                img_num[0] += 1
                if img and img.bytes:
                    try:
                        doc.add_picture(io.BytesIO(img.opt_bytes or img.bytes), width=Inches(5.5))
                        show_names = cfg.get("show_image_names", False)
                        cap_text = plain_text(m.caption)
                        if not cap_text and show_names:
                            cap_text = _build_caption(cfg.get("caption_format", "{name}"), img, img_num[0])
                        if cap_text:
                            doc.add_paragraph(cap_text)
                        if cfg.get("one_image_per_page"):
                            from docx.oxml import OxmlElement as _OE
                            from docx.oxml.ns import qn as _qn

                            p2 = doc.add_paragraph()
                            pPr = p2._p.get_or_add_pPr()
                            pb = _OE("w:pageBreakBefore")
                            pb.set(_qn("w:val"), "true")
                            pPr.append(pb)
                    except Exception:
                        doc.add_paragraph(f"[Image: {img.url}]")
                elif img:
                    doc.add_paragraph(f"[Image: {img.url}]")
            elif t == "bookmark":
                p = doc.add_paragraph()
                if r.keep_link(b.url):
                    hyperlink(p, b.url, b.url)
                else:
                    p.add_run(b.url)
            elif t == "media":
                m = b.media
                doc.add_paragraph("📎 " + (plain_text(m.caption) or m.name or m.url))
            elif t == "table":
                if b.rows:
                    width = max(len(x) for x in b.rows)
                    tb = doc.add_table(rows=len(b.rows), cols=width)
                    tb.style = "Table Grid"
                    for ri, row in enumerate(b.rows):
                        for ci, c in enumerate(row):
                            tb.cell(ri, ci).text = plain_text(c)
                kids = []
            elif t == "column_list":
                for c in kids:
                    add(c.children, depth)
                kids = []
            elif t in ("column", "synced"):
                add(kids, depth)
                kids = []
            elif t == "child_page":
                s = b.sub
                if s:
                    doc.add_heading("📄 " + s.title, level=2)
                    add(s.blocks, depth)
                else:
                    doc.add_paragraph("📄 " + b.title)
            elif t == "child_database":
                doc.add_paragraph("🗂 " + b.title + " (database)")
            elif t == "text":
                p = doc.add_paragraph()
                runs(p, b.text)
            if kids and t != "table":
                add(kids, depth + 1)

    add(tree)
    try:  # drop a trailing empty "page break" paragraph (would create a blank last page)
        last = doc.paragraphs[-1]
        if not last.text.strip() and last._p.xpath(".//w:pageBreakBefore"):
            last._p.getparent().remove(last._p)
    except Exception:
        pass
    doc.save(path)
