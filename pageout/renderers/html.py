"""HTML renderer (Notion-like stylesheet)."""

import html as _html
import os
import re
from functools import lru_cache
from urllib.parse import quote, unquote, urlparse

from pageout.core.assets import _load_custom_icon_data_uri
from pageout.core.config import FONT_CATEGORY, GOOGLE_FONTS, ICON_MODES, MATH_ENGINES, SAME_AS_BODY
from pageout.core.ir import LIST_KINDS, Asset, plain_text
from pageout.core.paths import resource_path

esc = _html.escape


TEXT_COLORS = {
    "gray": "#787774",
    "brown": "#9f6b53",
    "orange": "#d9730d",
    "yellow": "#cb912f",
    "green": "#448361",
    "blue": "#337ea9",
    "purple": "#9065b0",
    "pink": "#c14c8a",
    "red": "#d44c47",
}


BG_COLORS = {
    "gray": "#f1f1ef",
    "brown": "#f4eeee",
    "orange": "#fbecdd",
    "yellow": "#fbf3db",
    "green": "#edf3ec",
    "blue": "#e7f3f8",
    "purple": "#f6f3f9",
    "pink": "#faf1f5",
    "red": "#fdebec",
}


_FONT_STACKS = {
    "Sans-serif": "ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif",
    "Serif": "Georgia, Cambria, 'Times New Roman', Times, serif",
    "Monospace": "'Cascadia Code', Consolas, 'Courier New', Courier, monospace",
}


_FALLBACK_TAIL = {
    "sans": "'Segoe UI', Helvetica, Arial, sans-serif",
    "serif": "Georgia, 'Times New Roman', serif",
    "mono": "Consolas, 'Courier New', monospace",
    "arabic": "'Segoe UI', Tahoma, Arial, sans-serif",
}


def _safe_font_name(name):
    return re.sub(r"[^\w \-]", "", name or "").strip()


def _font_stack(name):
    if name in _FONT_STACKS:
        return _FONT_STACKS[name]
    n = _safe_font_name(name)
    if not n:
        return _FONT_STACKS["Sans-serif"]
    return f"'{n}', " + _FALLBACK_TAIL[FONT_CATEGORY.get(name, "sans")]


def _web_font_links(cfg):
    """<link> tags for Google Fonts (only when enabled; needs internet at export/view time)."""
    if not cfg.get("web_fonts"):
        return ""
    names = []
    for key in ("font_family", "heading_font"):
        n = cfg.get(key, "")
        if n in GOOGLE_FONTS and n not in names:
            names.append(n)
    if not names:
        return ""
    fam = "&".join("family=" + quote(n).replace("%20", "+") + ":wght@400;700" for n in names)
    return (
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?{fam}&display=swap">'
    )


KATEX_HEAD = (
    '<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.css">'
    '<script defer src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.js"></script>'
    "<script>window.addEventListener('load',function(){if(!window.katex)return;"
    "document.querySelectorAll('.eq').forEach(function(el){try{katex.render(el.textContent,el,"
    "{throwOnError:false,displayMode:el.tagName==='DIV'});}catch(e){}});});</script>"
)


_KATEX_RENDER = (
    "<script>window.addEventListener('load',function(){if(!window.katex)return;"
    "document.querySelectorAll('.eq').forEach(function(el){try{katex.render(el.textContent,el,"
    "{throwOnError:false,displayMode:el.tagName==='DIV'});}catch(e){}});});</script>"
)


@lru_cache(maxsize=1)
def _katex_bundle():
    """Inline KaTeX (JS + CSS with embedded fonts) from the bundled assets, or '' if missing."""
    try:
        base = resource_path("pageout/assets/katex")
        js = (base / "katex.min.js").read_text(encoding="utf-8").replace("</script", "<\\/script")
        css = (base / "katex.inline.css").read_text(encoding="utf-8")
    except Exception:
        return ""
    return f"<style>{css}</style><script>{js}</script>" + _KATEX_RENDER


_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


_CSS_TEMPLATE = r"""
/* ---- PageOut for Notion: Notion-like stylesheet ---- */
*, *::before, *::after { box-sizing: border-box; }
:root { --accent: @@ACCENT@@; --ink: #37352f; --muted: rgba(55,53,47,.65); --line: rgba(55,53,47,.09);
        --line2: #e9e9e7; --soft: #f7f6f3; --callout: rgba(241,241,239,.6); }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body {
  font-family: @@BODY_FONT@@, 'Segoe UI Emoji', 'Apple Color Emoji', 'Noto Color Emoji';
  max-width: 900px; margin: 2rem auto; padding: 0 1.6rem;
  color: var(--ink); line-height: @@LINE@@; font-size: @@SIZE@@px; text-align: @@ALIGN@@;
  -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility; font-kerning: normal;
  overflow-wrap: break-word;
}
/* Arabic / Hebrew paragraphs flow right-to-left automatically */
p, li, h1, h2, h3, blockquote, summary, td, th, figcaption, .callout-body { unicode-bidi: plaintext; }
p { margin: .28em 0; orphans: 3; widows: 3; }

/* title + icon */
.notion-page-icon { font-size: 78px; line-height: 1.1; display: block; text-align: @@HALIGN@@;
  margin: 0 0 .12em; user-select: none; }
.notion-page-icon img { height: 78px; width: auto; display: inline-block; vertical-align: bottom; }
h1.notion-title { font-family: @@HEAD_FONT@@; font-size: @@H1REM@@rem; font-weight: 700; line-height: 1.2;
  margin: 0 0 .25em; text-align: @@HALIGN@@; color: var(--ink); break-after: avoid; @@SEP@@ }

/* headings */
h1, h2, h3 { font-family: @@HEAD_FONT@@; font-weight: 600; line-height: 1.3; text-align: @@HALIGN@@;
  color: var(--accent); break-after: avoid; }
h1 { font-size: 1.875em; margin: 1.6em 0 .2em; }
h2 { font-size: 1.5em;   margin: 1.3em 0 .2em; }
h3 { font-size: 1.25em;  margin: 1.1em 0 .15em; }

a { color: var(--accent); text-decoration: underline; text-decoration-color: rgba(55,53,47,.4);
    text-decoration-thickness: .05em; text-underline-offset: 2px; }
strong { font-weight: 600; }

/* cover page */
.notion-cover-page { display: flex; flex-direction: column; justify-content: center; min-height: 60vh; padding: 3rem 0 2rem; }
.notion-page-break { page-break-after: always; break-after: page; height: 0; margin: 0; }
@media print { .notion-cover-page { min-height: 80vh; } }

/* properties (Notion style: plain key / value rows) */
table.props-table { border-collapse: collapse; margin: .7em 0 1.4em; width: 100%; font-size: .95em;
  border: none; border-bottom: 1px solid var(--line); }
table.props-table th { width: 24%; color: var(--muted); font-weight: 400; background: none; text-align: left;
  padding: .28em .8em .28em 0; border: none; vertical-align: top; }
table.props-table td { padding: .28em .3em; border: none; vertical-align: top; }
.props-pills { display: flex; flex-wrap: wrap; gap: .35em; margin: .7em 0 1.3em; }
.props-pills .pill { display: inline-flex; align-items: center; gap: .35em; background: var(--soft);
  border-radius: 4px; padding: .12em .6em; font-size: .85em; line-height: 1.5; }
.props-pills .pill-key { color: var(--muted); }
dl.props-list { margin: .6em 0 1.5em; display: grid; grid-template-columns: auto 1fr; gap: .2em 1.2em; font-size: .95em; }
dl.props-list dt { color: var(--muted); white-space: nowrap; }
dl.props-list dd { margin: 0; }

/* tables (Notion simple table) */
table { border-collapse: collapse; margin: 1em 0; width: 100%; font-size: .95em; }
thead { display: table-header-group; } tr { break-inside: avoid; }
td, th { border: 1px solid var(--line2); padding: .4em .65em; vertical-align: top; text-align: left; }
table:not(.props-table) th { background: var(--soft); font-weight: 500; }

/* quotes, code, callouts */
blockquote { border-left: 3px solid currentColor; margin: .6em 0; padding: 0 .9em; font-size: 1.2em; line-height: 1.5; }
pre { background: var(--soft); border-radius: 4px; padding: 1.5em 1.1em 1.5em 1.7em; overflow: auto;
  white-space: pre-wrap; word-break: break-word; font-size: .85em; line-height: 1.5; margin: .8em 0; tab-size: 2; }
code { background: rgba(135,131,120,.15); color: #eb5757; padding: .2em .4em; border-radius: 3px;
  font-family: @@CODE_FONT@@; font-size: 85%; }
pre, pre code { font-family: @@CODE_FONT@@; }
pre code { background: none; color: inherit; padding: 0; font-size: 1em; border-radius: 0; }
.callout { display: flex; gap: .7em; border-radius: 4px; padding: 1em 1em 1em .8em; margin: .8em 0;
  background: var(--callout); border: 1px solid var(--line2); }
.callout .callout-icon { font-size: 1.3em; line-height: 1.4; flex-shrink: 0; }
.callout .callout-body { flex: 1; min-width: 0; }
.callout .callout-body > :first-child { margin-top: 0; } .callout .callout-body > :last-child { margin-bottom: 0; }
details { margin: .3em 0; } summary { cursor: pointer; font-weight: 400; }
details > *:not(summary) { margin-left: 1.4em; }
.eq { font-family: 'Cambria Math', 'STIX Two Math', 'Times New Roman', serif; }
div.eq { text-align: center; margin: .9em 0; overflow-x: auto; }

/* images */
figure { margin: .8em 0; }
figure img { max-width: 100%; height: auto; border-radius: 3px; display: block; margin: 0 auto; }
figcaption { color: var(--muted); font-size: .85em; margin-top: .4em; text-align: center; }
.maximize-images figure img { width: 100%; object-fit: contain; }
.one-image-per-page figure { page-break-after: always; break-after: page; }

/* lists */
ul, ol { padding-left: 1.5em; margin: .2em 0; } li { margin: .1em 0; }
ul { list-style: disc; } ul ul { list-style: circle; } ul ul ul { list-style: square; }
ol { list-style: decimal; } ol ol { list-style: lower-alpha; } ol ol ol { list-style: lower-roman; }
ul.todo { list-style: none; padding-left: .2em; } ul.todo input { accent-color: var(--accent); margin-right: .4em; }
hr { border: none; border-top: 1px solid var(--line); margin: 1.2em 0; }
.indent { margin-left: 1.5em; }
.cols { display: flex; gap: 1.6em; } .col { flex: 1; min-width: 0; }
section.page { margin-bottom: 3em; } .subpage { margin-top: 2em; }

@media print {
  body { max-width: none; margin: 0; padding: 0; }
  pre, figure, .callout, blockquote { break-inside: avoid; }
}
"""


def _build_html_css(cfg: dict) -> str:
    """Full stylesheet built from the user's design settings."""
    body_font = _font_stack(cfg.get("font_family", "Sans-serif"))
    hf = cfg.get("heading_font", SAME_AS_BODY)
    head_font = body_font if hf in ("", SAME_AS_BODY) else _font_stack(hf)
    accent = cfg.get("accent_color", "#37352f")
    if not _HEX_RE.match(str(accent)):
        accent = "#37352f"
    size = int(cfg.get("base_font_size", 16))
    align = "justify" if str(cfg.get("text_align", "Left")).lower() == "justify" else "start"
    halign = "center" if str(cfg.get("heading_align", "Left")).lower() == "center" else "start"
    sep = "border-bottom: 3px solid var(--accent); padding-bottom: .3em;" if cfg.get("title_separator") else ""
    repl = {
        "@@ACCENT@@": accent,
        "@@BODY_FONT@@": body_font,
        "@@HEAD_FONT@@": head_font,
        "@@CODE_FONT@@": _FONT_STACKS["Monospace"],
        "@@LINE@@": str(float(cfg.get("line_spacing", 1.6))),
        "@@SIZE@@": str(size),
        "@@ALIGN@@": align,
        "@@HALIGN@@": halign,
        "@@H1REM@@": str(round(2.5 * size / 16, 2)),
        "@@SEP@@": sep,
    }
    css = _CSS_TEMPLATE
    for k, v in repl.items():
        css = css.replace(k, v)
    return css


def color_style(color):
    if not color or color == "default":
        return ""
    if color.endswith("_background"):
        c = BG_COLORS.get(color[:-11])
        return f"background:{c};" if c else ""
    c = TEXT_COLORS.get(color)
    return f"color:{c};" if c else ""


def props_html(rows, layout: str, cfg: dict) -> str:
    """Render property rows according to the chosen layout style."""
    if not rows or layout == "Hidden":
        return ""
    if layout == "Notion Table":
        inner = "".join(f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in rows)
        return f'<table class="props-table">{inner}</table>'
    if layout == "Inline Pills":
        pills = "".join(
            f'<span class="pill"><span class="pill-key">{esc(k)}:</span><span class="pill-val">{esc(v)}</span></span>'
            for k, v in rows
        )
        return f'<div class="props-pills">{pills}</div>'
    if layout == "Minimalist List":
        items = "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in rows)
        return f'<dl class="props-list">{items}</dl>'
    return ""


def _page_icon_html(doc, cfg: dict) -> str:
    """Return an HTML snippet for the page icon based on icon_mode setting."""
    mode = cfg.get("icon_mode", ICON_MODES[0])
    if mode == "Hide icon":
        return ""
    if mode == "Custom icon file":
        path = cfg.get("icon_custom_file", "")
        if path:
            uri = _load_custom_icon_data_uri(path)
            if uri:
                return f'<span class="notion-page-icon"><img src="{esc(uri, quote=True)}" alt="icon"></span>'
    if doc:
        if doc.icon_emoji:
            return f'<span class="notion-page-icon">{esc(doc.icon_emoji)}</span>'
        if doc.icon_url:
            return f'<span class="notion-page-icon"><img src="{esc(doc.icon_url, quote=True)}" alt="icon"></span>'
    return ""


def _build_caption(fmt_template: str, img, img_num: int) -> str:
    """Build an image caption from the template (img is an Asset)."""
    url = img.url or ""
    base = os.path.basename(unquote(urlparse(url).path))
    name, _ext = os.path.splitext(base)
    ext = (_ext.lstrip(".")) if _ext else (img.ext or ".png").lstrip(".")
    result = fmt_template
    result = result.replace("{name}", name or base)
    result = result.replace("{ext}", ext)
    result = result.replace("{n}", str(img_num))
    result = result.replace("{original}", name)
    result = result.replace("{caption}", img.caption or "")
    return result


def rt_html(rts, r):
    out = []
    for x in rts or []:
        if x.equation is not None:
            s = f'<span class="eq">{esc(x.equation)}</span>'
        else:
            s = esc(x.text).replace("\n", "<br>")
        if x.code:
            s = f"<code>{s}</code>"
        if x.bold:
            s = f"<strong>{s}</strong>"
        if x.italic:
            s = f"<em>{s}</em>"
        if x.strike:
            s = f"<s>{s}</s>"
        if x.underline:
            s = f"<u>{s}</u>"
        st = color_style(x.color)
        if st:
            s = f'<span style="{st}">{s}</span>'
        href = r.href_for(x)
        if href:
            s = f'<a href="{esc(href, quote=True)}">{s}</a>'
        out.append(s)
    return "".join(out)


def blocks_html(blocks, r, img_counter=None):
    if img_counter is None:
        img_counter = [0]
    out, i = [], 0
    while i < len(blocks):
        b = blocks[i]
        t = b.kind
        if t in LIST_KINDS:
            tag = "ol" if t == "numbered" else "ul"
            cls = ' class="todo"' if t == "todo" else ""
            items = []
            while i < len(blocks) and blocks[i].kind == t:
                bb = blocks[i]
                inner = rt_html(bb.text, r)
                if t == "todo":
                    chk = " checked" if bb.checked else ""
                    inner = f'<input type="checkbox" disabled{chk}> ' + inner
                items.append(f"<li>{inner}{blocks_html(bb.children, r, img_counter)}</li>")
                i += 1
            out.append(f"<{tag}{cls}>{''.join(items)}</{tag}>")
            continue
        out.append(block_html(b, r, img_counter))
        i += 1
    return "\n".join(x for x in out if x)


def block_html(b, r, img_counter=None):
    if img_counter is None:
        img_counter = [0]
    t = b.kind
    kids = b.children
    cfg = r.cfg

    def rt():
        return rt_html(b.text, r)

    def sub():
        return blocks_html(kids, r, img_counter)

    def indent():
        return f'<div class="indent">{sub()}</div>' if kids else ""

    if t == "paragraph":
        return f"<p>{rt() or '<br>'}</p>" + indent()
    if t == "heading":
        return f"<h{b.level}>{rt()}</h{b.level}>" + indent()
    if t == "toggle":
        op = " open" if r.expand else ""
        return f"<details{op}><summary>{rt()}</summary>{sub()}</details>"
    if t == "quote":
        return f"<blockquote>{rt()}{sub()}</blockquote>"
    if t == "callout":
        emoji = b.icon or "💡"
        st = color_style(b.color)
        st_ = f' style="{st}"' if st else ""
        return (
            f'<div class="callout"{st_}>'
            f'<span class="callout-icon">{esc(emoji)}</span>'
            f'<div class="callout-body">{rt()}{sub()}</div></div>'
        )
    if t == "code":
        lang = esc(b.language)
        cap = rt_html(b.caption, r)
        return f'<pre><code class="language-{lang}">{esc(plain_text(b.text))}</code></pre>' + (
            f"<p><em>{cap}</em></p>" if cap else ""
        )
    if t == "divider":
        return "<hr>"
    if t == "equation":
        return f'<div class="eq">{esc(b.expression)}</div>'
    if t == "image":
        m = b.media
        if not m or not m.url:
            return ""
        img = m.asset or Asset(url=m.url)
        img_counter[0] += 1
        num = img_counter[0]
        notion_cap = rt_html(m.caption, r)
        show_names = cfg.get("show_image_names", False)
        caption_html = ""
        if show_names and not notion_cap:
            cap_text = _build_caption(cfg.get("caption_format", "{name}"), img, num)
            caption_html = f"<figcaption>{esc(cap_text)}</figcaption>"
        elif notion_cap:
            caption_html = f"<figcaption>{notion_cap}</figcaption>"
        one_per = cfg.get("one_image_per_page", False)
        style = ' style="page-break-after:always;break-after:page;"' if one_per else ""
        return (
            f'<figure{style}><img src="{esc(r.img_src(img), quote=True)}" '
            f'alt="{esc(plain_text(m.caption))}">' + caption_html + "</figure>"
        )
    if t == "media":
        m = b.media
        name = m.display_name()
        if m.external and r.keep_link(m.url):
            return f'<p>📎 <a href="{esc(m.url, quote=True)}">{esc(name)}</a></p>'
        return f"<p>📎 {esc(name)}</p>"
    if t == "bookmark":
        text = plain_text(b.caption) or b.url
        if r.keep_link(b.url):
            return f'<p>🔗 <a href="{esc(b.url, quote=True)}">{esc(text)}</a></p>'
        return f"<p>🔗 {esc(text)}</p>"
    if t == "table":
        hdr, rhdr = b.col_header, b.row_header
        s = ["<table>"]
        for ri, row in enumerate(b.rows):
            cells = []
            for ci, c in enumerate(row):
                tag = "th" if (hdr and ri == 0) or (rhdr and ci == 0) else "td"
                cells.append(f"<{tag}>{rt_html(c, r)}</{tag}>")
            s.append("<tr>" + "".join(cells) + "</tr>")
        s.append("</table>")
        return "".join(s)
    if t == "column_list":
        cols = "".join(f'<div class="col">{blocks_html(c.children, r, img_counter)}</div>' for c in kids)
        return f'<div class="cols">{cols}</div>'
    if t in ("column", "synced"):
        return sub()
    if t == "child_page":
        s = b.sub
        if s:
            return (
                f'<section class="subpage"><h2>📄 {esc(s.title)}</h2>{blocks_html(s.blocks, r, img_counter)}</section>'
            )
        return f'<p class="subpage">📄 {esc(b.title)}</p>'
    if t == "child_database":
        return f'<p class="subpage">🗂 {esc(b.title)} (database)</p>'
    if t == "link_to_page":
        pl = r.page_link(b.target_id)
        if pl:
            return f'<p>↪ <a href="{esc(pl[0], quote=True)}">{esc(pl[1])}</a></p>'
        return "<p>↪ linked page</p>"
    if t == "text":
        return f"<p>{rt()}</p>" + indent()
    return ""


def wrap_html(title, body, cfg):
    css = _build_html_css(cfg) + (cfg.get("custom_css") or "")
    body_classes = []
    if cfg.get("maximize_images"):
        body_classes.append("maximize-images")
    if cfg.get("one_image_per_page"):
        body_classes.append("one-image-per-page")
    cls_attr = f' class="{" ".join(body_classes)}"' if body_classes else ""
    head_extra = _web_font_links(cfg)
    if cfg.get("render_math", True) and 'class="eq"' in body:
        engine = cfg.get("math_engine", MATH_ENGINES[0])
        if engine == MATH_ENGINES[0]:
            head_extra += _katex_bundle() or KATEX_HEAD  # offline; falls back to the CDN
        elif engine == MATH_ENGINES[1]:
            head_extra += KATEX_HEAD
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{esc(title)}</title>{head_extra}<style>{css}</style></head>"
        f"<body{cls_attr}>{body}</body></html>"
    )
