"""LaTeX renderer."""

import os
import re
from urllib.parse import unquote, urlparse

from pageout.core.config import LATEX_IMG_MODES
from pageout.core.ir import LIST_KINDS, Asset, plain_text
from pageout.ocr.gemini import collect_page_images, transcribe_whiteboard_images
from pageout.renderers.html import _build_caption

_TEX_MAP = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


_EMOJI_RE = re.compile("[\U0001f000-\U0001faff\u2600-\u27bf\ufe0f\u200d]")


def escape_tex(s: str) -> str:
    """Escape LaTeX specials in ONE pass (a sequential replace would re-escape the braces
    of \\textbackslash{}) and drop emoji, which pdflatex cannot typeset."""
    if not s:
        return ""
    s = _EMOJI_RE.sub("", s)
    return re.sub(r"[\\&%$#_{}~^]", lambda m: _TEX_MAP[m.group()], s)


def rt_tex(rts, r):
    out = []
    for x in rts or []:
        if x.equation is not None:
            s = f"${x.equation}$"
        else:
            s = escape_tex(x.text).replace("\n", " ")
        if x.code:
            s = f"\\texttt{{{s}}}"
        if x.bold:
            s = f"\\textbf{{{s}}}"
        if x.italic:
            s = f"\\textit{{{s}}}"
        if x.strike:
            s = f"\\sout{{{s}}}"
        if x.underline:
            s = f"\\underline{{{s}}}"
        href = r.href_for(x)
        if href:
            safe_href = href.replace("%", "\\%").replace("#", "\\#")
            s = f"\\href{{{safe_href}}}{{{s}}}"
        out.append(s)
    return "".join(out)


def props_tex(rows, layout: str) -> str:
    if not rows or layout == "Hidden":
        return ""
    if layout == "Notion Table":
        rows_tex = "".join(f"  \\textbf{{{escape_tex(k)}}} & {escape_tex(v)} \\\\\n  \\hline\n" for k, v in rows)
        return (
            "\\begin{center}\n"
            "\\begin{tabular}{|r|l|}\n"
            "  \\hline\n"
            f"{rows_tex}"
            "\\end{tabular}\n"
            "\\end{center}\n\\medskip\n\n"
        )
    if layout == "Inline Pills":
        pills = " \\quad ".join(f"\\textbf{{{escape_tex(k)}:}} {escape_tex(v)}" for k, v in rows)
        return f"\\noindent {pills}\n\\par\\medskip\n\n"
    if layout == "Minimalist List":
        items = "".join(f"  \\item[\\textbf{{{escape_tex(k)}}}] {escape_tex(v)}\n" for k, v in rows)
        return f"\\begin{{description}}\n{items}\\end{{description}}\n\\medskip\n\n"
    return ""


def blocks_tex(blocks, r, doc, base_dir, log_fn=None, img_counter=None, page_ocr=None):
    if img_counter is None:
        img_counter = [0]
    out, i = [], 0
    cfg = r.cfg

    if page_ocr is None and cfg.get("gemini_math_ocr"):
        page_tree = (doc.blocks if doc is not None else None) or blocks
        page_images = collect_page_images(page_tree)
        if page_images:
            key = cfg.get("gemini_api_key", "").strip()
            model = cfg.get("gemini_model", "gemini-3.5-flash-lite")
            if log_fn:
                log_fn(
                    f"  [Math OCR] Found {len(page_images)} whiteboard image(s) on page. Starting single multimodal transcription..."
                )
            try:
                transcription, used_model = transcribe_whiteboard_images(page_images, key, model, log_fn)
                page_ocr = {"text": transcription, "model": used_model, "error": None, "emitted": False}
            except Exception as err:
                if log_fn:
                    log_fn(f"  [Math OCR Error] {err}")
                page_ocr = {"text": "", "model": model, "error": str(err), "emitted": False}
        else:
            page_ocr = {"text": "", "model": "", "error": None, "emitted": False}

    while i < len(blocks):
        b = blocks[i]
        t = b.kind
        if t in LIST_KINDS:
            env = "enumerate" if t == "numbered" else "itemize"
            items = []
            while i < len(blocks) and blocks[i].kind == t:
                bb = blocks[i]
                inner = rt_tex(bb.text, r)
                if t == "todo":
                    chk = "$\\boxtimes$" if bb.checked else "$\\square$"
                    inner = f"[{chk}] {inner}"
                else:
                    inner = f" {inner}"
                kids_tex = blocks_tex(bb.children, r, doc, base_dir, log_fn, img_counter, page_ocr)
                items.append(f"  \\item{inner}\n{kids_tex}")
                i += 1
            out.append(f"\\begin{{{env}}}\n{''.join(items)}\\end{{{env}}}\n")
            continue

        kids = b.children

        def sub():
            return blocks_tex(kids, r, doc, base_dir, log_fn, img_counter, page_ocr)

        if t in ("paragraph", "text", "toggle"):
            p = rt_tex(b.text, r)
            if t == "toggle" and p.strip():
                p = f"\\textbf{{{p}}}"
            if p.strip():
                out.append(f"{p}\\par\\medskip\n{sub()}")
            elif kids:
                out.append(sub())
        elif t == "heading":
            h = rt_tex(b.text, r)
            cmd = {1: "section", 2: "subsection", 3: "subsubsection"}[b.level]
            out.append(f"\\{cmd}*{{{h}}}\n{sub()}")
        elif t == "quote":
            q = rt_tex(b.text, r)
            out.append(f"\\begin{{quote}}\n{q}\n{sub()}\\end{{quote}}\n")
        elif t == "callout":
            icon_tex = escape_tex(b.icon).strip()  # emoji cannot be typeset by pdflatex -> dropped
            prefix = f"\\textbf{{{icon_tex}}} " if icon_tex else ""
            c_text = rt_tex(b.text, r)
            out.append(f"\\begin{{quote}}\n{prefix}{c_text}\n{sub()}\\end{{quote}}\n")
        elif t == "code":
            raw_code = plain_text(b.text)
            cap = plain_text(b.caption)
            cap_line = f"\n% Caption: {cap}" if cap else ""
            out.append(f"\\begin{{verbatim}}{cap_line}\n{raw_code}\n\\end{{verbatim}}\n")
        elif t == "divider":
            out.append("\\noindent\\rule{\\linewidth}{0.4pt}\\par\\medskip\n")
        elif t == "equation":
            out.append(f"\\begin{{equation*}}\n{b.expression}\n\\end{{equation*}}\n")
        elif t == "table":
            rows = b.rows
            if rows:
                col_count = max(len(row) for row in rows)
                spec = "|" + "l|" * col_count
                t_lines = [f"\\begin{{center}}\n\\begin{{tabular}}{{{spec}}}\n\\hline"]
                for row in rows:
                    cells = [rt_tex(c, r) for c in row]
                    cells += [""] * (col_count - len(cells))
                    t_lines.append(" & ".join(cells) + " \\\\\n\\hline")
                t_lines.append("\\end{tabular}\n\\end{center}\n")
                out.append("\n".join(t_lines))
        elif t == "image":
            m = b.media
            img_counter[0] += 1
            cur_img_num = img_counter[0]
            img = None
            if m and m.url:
                img = m.asset or Asset(url=m.url, n=cur_img_num)

            if page_ocr and not page_ocr.get("emitted"):
                page_ocr["emitted"] = True
                if page_ocr.get("text"):
                    out.append(
                        f"\n% --- Transcribed Math Whiteboard (Gemini OCR: {page_ocr['model']}) ---\n"
                        f"{page_ocr['text']}\n"
                        f"% --- End Transcribed Math ---\n\n"
                    )
                elif page_ocr.get("error"):
                    out.append(f"\n% [Math OCR Failed on lecture images: {escape_tex(page_ocr['error'])}]\n")

            if page_ocr and page_ocr.get("text") and not cfg.get("keep_whiteboard_image"):
                i += 1
                continue

            if cfg.get("latex_images") == LATEX_IMG_MODES[1]:
                nm = os.path.basename(unquote(urlparse(img.url if img else "").path)) or "image"
                out.append(f"% [Image {cur_img_num} omitted: {nm.replace(chr(10), ' ')}]\n")
                i += 1
                continue

            img_path = img.path if img else None
            if img_path and os.path.splitext(img_path)[1].lower() not in (".png", ".jpg", ".jpeg", ".pdf"):
                out.append(
                    f"% [Image format not supported by LaTeX, convert to PNG/JPG: {os.path.basename(img_path)}]\n"
                )
            elif img_path and os.path.exists(img_path):
                rel_path = os.path.relpath(img_path, base_dir).replace("\\", "/")
                cap = plain_text(m.caption)
                if not cap and cfg.get("show_image_names"):
                    cap = _build_caption(cfg.get("caption_format", "{name}"), img, cur_img_num)
                cap_tex = f"\\caption{{{escape_tex(cap)}}}" if cap else ""
                fig_tex = (
                    "\\begin{figure}[htbp]\n"
                    "\\centering\n"
                    f"\\includegraphics[width=0.85\\linewidth]{{{rel_path}}}\n"
                    f"{cap_tex}\n"
                    "\\end{figure}\n\n"
                )
                out.append(fig_tex)
            elif img and img.url:
                out.append(f"% [Image: {img.url}]\n")
        elif t == "media":
            m = b.media
            name = plain_text(m.caption) or m.name or "Attachment"
            out.append(f"\\texttt{{[Attachment: {escape_tex(name)}]}}\\par\\medskip\n")
        elif t == "bookmark":
            url = b.url
            text = plain_text(b.caption) or url
            if r.keep_link(url):
                safe_url = url.replace("%", "\\%").replace("#", "\\#")
                out.append(f"\\href{{{safe_url}}}{{{escape_tex(text)}}}\\par\\medskip\n")
            else:
                out.append(f"{escape_tex(text)}\\par\\medskip\n")
        elif t == "child_page":
            s = b.sub
            if s:
                out.append(
                    f"\\subsection*{{{escape_tex(s.title)}}}\n"
                    + blocks_tex(s.blocks, r, doc, base_dir, log_fn, img_counter, page_ocr)
                )
            else:
                out.append(f"\\textit{{[Child Page: {escape_tex(b.title)}]}}\\par\\medskip\n")
        elif t == "child_database":
            out.append(f"\\textit{{[Database: {escape_tex(b.title)}]}}\\par\\medskip\n")
        elif t in ("column_list", "column", "synced"):
            out.append(sub())

        i += 1
    return "".join(out)


def build_complete_latex(title: str, prop_rows: list, body_tex: str, cfg: dict) -> str:
    """Wraps body LaTeX in a clean, complete, compilable LaTeX article document."""
    escaped_title = escape_tex(title)
    props_block = props_tex(prop_rows, cfg.get("prop_layout", "Notion Table"))
    cover_page_break = "\\newpage\n\n" if cfg.get("cover_page") else ""

    doc = [
        "\\documentclass[11pt,a4paper]{article}",
        "% Compile with pdflatex (Latin text). For Arabic/CJK use xelatex or lualatex.",
        "\\usepackage[utf8]{inputenc}",
        "\\usepackage[T1]{fontenc}",
        "\\usepackage[margin=1in]{geometry}",
        "\\usepackage{amsmath,amssymb,amsthm}",
        "\\usepackage{graphicx}",
        "\\usepackage[normalem]{ulem}",
        "\\usepackage{xcolor}",
        "\\usepackage{hyperref}",
        "",
        "\\hypersetup{",
        "    colorlinks=true,",
        "    linkcolor=blue,",
        "    filecolor=magenta,",
        "    urlcolor=blue,",
        f"    pdftitle={{{escaped_title}}},",
        "}",
        "",
        f"\\title{{{escaped_title}}}",
        "\\author{}",
        "\\date{\\today}",
        "",
        "\\begin{document}",
        "\\maketitle",
        "",
        props_block,
        cover_page_break,
        body_tex,
        "\\end{document}",
        "",
    ]
    return "\n".join(doc)
