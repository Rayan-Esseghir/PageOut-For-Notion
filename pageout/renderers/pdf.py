"""PDF engines (Playwright): API-HTML printing, Browser engine, blank-page removal."""

import os
import re

from playwright.sync_api import sync_playwright

from pageout.core import paths as _paths  # noqa: F401  (side effect: portable Chromium folder)
from pageout.core.config import DEFAULTS, LINK_MODES, PAGENUM_FMT, PAGENUM_POS, PROFILE_DIR
from pageout.core.errors import LoginRequired

STEALTH_ARGS = ["--disable-blink-features=AutomationControlled"]


_PAINT_RE = re.compile(rb"(?<![A-Za-z0-9_/.\-])(?:f\*?|F|S|s|B\*?|b\*?|sh|Do|Tj|TJ)(?![A-Za-z0-9_])")


def _page_is_blank(page):
    """True when a PDF page has no text, no images and nothing painted."""
    try:
        if (page.extract_text() or "").strip():
            return False
    except Exception:
        return False
    try:
        if len(page.images):
            return False
    except Exception:
        pass
    try:
        contents = page.get_contents()
        if contents is None:
            return True
        return not _PAINT_RE.search(contents.get_data())
    except Exception:
        return False


def remove_blank_pages(path):
    """Delete empty pages from a PDF file in place. Returns how many were removed."""
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        from PyPDF2 import PdfReader, PdfWriter
    reader = PdfReader(path)
    keep = [i for i, pg in enumerate(reader.pages) if not _page_is_blank(pg)]
    removed = len(reader.pages) - len(keep)
    if not keep or removed == 0:
        return 0
    w = PdfWriter()
    for i in keep:
        w.add_page(reader.pages[i])
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        w.write(f)
    os.replace(tmp, path)
    return removed


BASE_CSS = """
@media print {
  html, body, .notion-app-inner, .notion-frame, .notion-scroller,
  .notion-page-content { height: auto !important; overflow: visible !important; }
}
"""


CLEAN_CSS = """
.notion-topbar, .notion-topbar-mobile, .notion-sidebar-container,
.notion-help-button, .notion-overlay-container { display: none !important; }
"""


EXPAND_JS = """() => {
  const b = [...document.querySelectorAll(
    '.notion-page-content [role="button"][aria-expanded="false"]')];
  b.forEach(x => x.click());
  return b.length;
}"""


SCROLL_JS = """async () => {
  const sc = [...document.querySelectorAll('.notion-scroller')]
    .filter(e => e.scrollHeight > e.clientHeight);
  for (const s of sc) {
    for (let y = 0; y < s.scrollHeight; y += 700) {
      s.scrollTop = y;
      await new Promise(r => setTimeout(r, 120));
    }
    s.scrollTop = 0;
  }
}"""


IMAGES_JS = """async () => {
  const imgs = [...document.images].filter(i => !i.complete);
  await Promise.race([
    Promise.all(imgs.map(i => new Promise(r => { i.onload = i.onerror = r; }))),
    new Promise(r => setTimeout(r, 15000))
  ]);
}"""


HIDE_PROPS_JS = """(args) => {
  const hide = args.hide, allSet = new Set(args.all);
  const content = document.querySelector('.notion-page-content');
  const leaves = [...document.querySelectorAll('div,span')].filter(e =>
    e.children.length === 0 && allSet.has(e.textContent.trim()) &&
    !(content && content.contains(e)));
  for (const leaf of leaves) {
    if (!hide.includes(leaf.textContent.trim())) continue;
    let el = leaf;
    for (let i = 0; i < 6 && el.parentElement; i++) {
      const parent = el.parentElement;
      const other = leaves.some(o => o !== leaf && parent.contains(o) && !el.contains(o));
      if (other) { el.style.display = 'none'; break; }
      el = parent;
    }
  }
}"""


LINKS_JS = """(mode) => document.querySelectorAll('a[href]').forEach(a => {
  const h = a.getAttribute('href') || '';
  const internal = h.startsWith('/') || /^https?:\\/\\/(www\\.)?notion\\.(so|site)/.test(h);
  if (mode === 'all' || (mode === 'internal' && internal)) a.removeAttribute('href');
})"""


def _pagenum_templates(cfg: dict):
    """Return (header_template, footer_template) based on position/format settings."""
    pos = cfg.get("page_num_position", PAGENUM_POS[0])
    fmt = cfg.get("page_num_format", PAGENUM_FMT[0])

    if fmt == "Page X of Y":
        content = (
            '<span style="font-size:9px;color:#666">'
            'Page <span class="pageNumber"></span>'
            ' of <span class="totalPages"></span></span>'
        )
    else:
        content = '<span style="font-size:9px;color:#666"><span class="pageNumber"></span></span>'

    align_map = {
        "Bottom Center": "center",
        "Bottom Right": "right",
        "Top Right": "right",
    }
    align = align_map.get(pos, "center")
    wrapped = f'<div style="width:100%;text-align:{align}">{content}</div>'

    if pos == "Top Right":
        return wrapped, "<span></span>"
    return "<span></span>", wrapped


def _running_header_templates(cfg: dict):
    """Return (header_template, footer_template) for running headers with page titles."""
    header_fmt = cfg.get("header_format", "{title}")
    pos = cfg.get("page_num_position", PAGENUM_POS[0])
    fmt = cfg.get("page_num_format", PAGENUM_FMT[0])

    # Page number content for footer
    if fmt == "Page X of Y":
        page_content = (
            '<span style="font-size:9px;color:#666">'
            'Page <span class="pageNumber"></span>'
            ' of <span class="totalPages"></span></span>'
        )
    else:
        page_content = '<span style="font-size:9px;color:#666"><span class="pageNumber"></span></span>'

    # Format the header format string - replace {title} placeholder with page-title span
    # Use string formatting to inject the page title element
    title_placeholder = '<span class="page-title">'
    formatted_header = header_fmt.replace("{title}", title_placeholder + "</span>")

    # Running header with page title
    header_content = (
        '<div style="width:100%;text-align:center;'
        "font-size:9px;color:#666;vertical-align:middle;"
        'height:15mm;display:flex;align-items:center;justify-content:center;">'
        '<span id="page-title" style="max-width:90vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
        + f"{formatted_header}"
        + "</span></div>"
    )

    # Footer position
    align = {"Bottom Center": "center", "Bottom Right": "right", "Top Right": "right"}.get(pos, "center")
    footer_content = f'<div style="width:100%;text-align:{align}">{page_content}</div>'

    # Always return the header content with page title
    return header_content, footer_content


TOC_JS = """() => {
  const toc = document.createElement('div');
  toc.id = 'notion-toc';
  toc.style.cssText = 'position:fixed;bottom:0;left:0;right:0;background:#f7f6f3;border-top:1px solid #e9e9e7;padding:1em 2em;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;font-size:14px;z-index:9999;';

  const items = [];
  document.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach((h, i) => {
    const text = h.textContent.trim();
    if (text.length > 0) {
      items.push({level: parseInt(h.tagName[1]), text: text, id: h.id || 'toc-' + i});
      if (!h.id) h.id = h.id || 'toc-' + i;
    }
  });

  if (items.length === 0) return;

  let html = '<strong>Table of Contents</strong><br><span style="font-size:13px;color:#555;">(' + items.length + ' sections)</span><br>';
  items.forEach(item => {
    const indent = '█'.repeat(item.level - 1);
    html += '<a href="#' + item.id + '" style="text-decoration:none;color:#2563eb;">' + indent + ' ' + item.text + '</a><br>';
  });
  toc.innerHTML = html;

  const target = document.querySelector('.notion-app-inner') || document.body;
  target.parentNode.insertBefore(toc, target);
  return items.length;
}"""


WATERMARK_CSS = """
body::before {{
  content: "@@@WATERMARK@@@";
  position: fixed;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%) rotate(-45deg);
  font-size: 48px;
  color: rgba(0,0,0,@@@OPACITY@@@);
  opacity: 0@@@OPACITY@@@;
  pointer-events: none;
  z-index: 9999;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  font-weight: 400;
}}
"""


PAGE_TITLE_JS = """() => {
  const titleEl = document.querySelector('h1.notion-title, .notion-title, [data-type="header_1"]');
  if (titleEl) {
    const title = titleEl.textContent.trim().substring(0, 100);
    // Store for potential use in headers
    window.__pageTitle = title;
    return title;
  }
  return '';
}"""


BOOKLET_CSS = """
@page {
  size: A5;
  margin: 10mm;
}
"""


def pdf_kwargs(cfg, path):
    m = f"{int(cfg['margin_mm'])}mm"
    margin = {"top": m, "bottom": m, "left": m, "right": m}

    # Handle booklet mode (A5)
    format_size = cfg["page_size"]
    landscape = cfg["orientation"] == "Landscape"
    if cfg.get("booklet_mode", False):
        # Booklet mode uses A5 size regardless of selected size
        format_size = "A5"

    kw = dict(
        path=path,
        format=format_size,
        landscape=landscape,
        print_background=bool(cfg["print_background"]),
        scale=max(0.1, min(2.0, float(cfg["scale"]) / 100)),
    )

    # Running header with page title
    if cfg.get("running_header", False):
        margin["top"] = f"{max(int(cfg['margin_mm']), 15)}mm"
        hdr, ftr = _running_header_templates(cfg)
        kw.update(display_header_footer=True, header_template=hdr, footer_template=ftr)
    elif cfg.get("page_numbers", False):
        pos = cfg.get("page_num_position", PAGENUM_POS[0])
        if pos == "Top Right":
            margin["top"] = f"{max(int(cfg['margin_mm']), 15)}mm"
        else:
            margin["bottom"] = f"{max(int(cfg['margin_mm']), 15)}mm"
        hdr, ftr = _pagenum_templates(cfg)
        kw.update(display_header_footer=True, header_template=hdr, footer_template=ftr)

    kw["margin"] = margin
    return kw


def launch_context(pw, cfg, headless=True):
    scheme = "light" if cfg.get("light_theme", True) else "no-preference"
    viewport = {"width": 1280, "height": 1000}
    if cfg.get("use_login", True):
        os.makedirs(PROFILE_DIR, exist_ok=True)
        ctx = pw.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=headless,
            color_scheme=scheme,
            viewport=viewport,
            args=STEALTH_ARGS,
            ignore_default_args=["--enable-automation"],
        )
        return None, ctx
    browser = pw.chromium.launch(headless=headless)
    return browser, browser.new_context(color_scheme=scheme, viewport=viewport)


def login_to_notion(log):
    """Opens a visible browser; log in, then close the window."""
    cfg = dict(DEFAULTS)
    cfg["use_login"] = True
    with sync_playwright() as pw:
        _, ctx = launch_context(pw, cfg, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.notion.so/login")
        log("Log in to Notion in the browser window, then close the window.")
        try:
            while True:
                page.wait_for_timeout(1000)
        except Exception:
            pass
        try:
            ctx.close()
        except Exception:
            pass
    log("Login session saved.")


def render_notion_page(page, pid, path, cfg, all_props, hide_names):
    """Browser engine: print the real Notion page."""
    page.goto(f"https://www.notion.so/{pid.replace('-', '')}", wait_until="domcontentloaded", timeout=60000)
    if "/login" in page.url:
        raise LoginRequired()
    page.wait_for_selector(".notion-page-content", timeout=45000)
    page.wait_for_timeout(1000)
    if cfg["expand_toggles"]:
        for _ in range(8):
            if not page.evaluate(EXPAND_JS):
                break
            page.wait_for_timeout(600)
    page.evaluate(SCROLL_JS)
    page.evaluate(IMAGES_JS)
    page.wait_for_timeout(int(float(cfg["extra_wait"]) * 1000))

    # Build CSS with optional improvements
    css_parts = [BASE_CSS]

    # Cover page CSS
    if cfg.get("cover_page_improved", False):
        css_parts.append("""
.notion-cover-page {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  min-height: 80vh;
  padding: 4rem 2rem;
  text-align: center;
  background: linear-gradient(135deg, #f7f6f3 0%, #e9e9e7 100%);
}
.notion-cover-page h1 {
  font-size: 2.5cm;
  margin: 0 0 1rem;
  color: #37352f;
}
.notion-cover-page .notion-page-icon {
  font-size: 120px;
  margin: 0 0 0.5rem;
}
.notion-cover-page .props-table,
.notion-cover-page .props-pills,
.notion-cover-page .props-list {
  opacity: 0.8;
}
""")

    # Watermark CSS
    if cfg.get("watermark_text", "").strip():
        wm_text = cfg.get("watermark_text", "").strip()
        wm_opacity = cfg.get("watermark_opacity", 0.15)
        # Escape any special CSS characters in watermark text
        wm_text_escaped = wm_text.replace("\\", "\\\\").replace('"', '\\"')
        watermark_css = WATERMARK_CSS.replace("@@@WATERMARK@@@", wm_text_escaped)
        watermark_css = watermark_css.replace("@@@OPACITY@@@", str(wm_opacity))
        css_parts.append(watermark_css)

    # Booklet mode CSS
    if cfg.get("booklet_mode", False):
        css_parts.append(BOOKLET_CSS)

    # Clean layout
    if cfg.get("clean_layout", True):
        css_parts.append(CLEAN_CSS)

    # Custom CSS
    custom_css = cfg.get("custom_css") or ""
    if custom_css:
        css_parts.append(custom_css)

    css = "\n".join(css_parts)
    page.add_style_tag(content=css)

    # Generate Table of Contents if enabled
    if cfg.get("table_of_contents", False):
        page.evaluate(TOC_JS)

    if hide_names:
        page.evaluate(HIDE_PROPS_JS, {"hide": hide_names, "all": all_props})
    mode = {LINK_MODES[1]: "all", LINK_MODES[2]: "internal"}.get(cfg["links"])
    if mode:
        page.evaluate(LINKS_JS, mode)
    page.pdf(**pdf_kwargs(cfg, path))
