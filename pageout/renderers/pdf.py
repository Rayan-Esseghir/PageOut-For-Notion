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


def pdf_kwargs(cfg, path):
    m = f"{int(cfg['margin_mm'])}mm"
    margin = {"top": m, "bottom": m, "left": m, "right": m}
    kw = dict(
        path=path,
        format=cfg["page_size"],
        landscape=(cfg["orientation"] == "Landscape"),
        print_background=bool(cfg["print_background"]),
        scale=max(0.1, min(2.0, float(cfg["scale"]) / 100)),
    )
    if cfg["page_numbers"]:
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
    css = BASE_CSS + (CLEAN_CSS if cfg["clean_layout"] else "") + (cfg.get("custom_css") or "")
    page.add_style_tag(content=css)
    if hide_names:
        page.evaluate(HIDE_PROPS_JS, {"hide": hide_names, "all": all_props})
    mode = {LINK_MODES[1]: "all", LINK_MODES[2]: "internal"}.get(cfg["links"])
    if mode:
        page.evaluate(LINKS_JS, mode)
    page.pdf(**pdf_kwargs(cfg, path))
