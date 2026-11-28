"""EPUB renderer (reads IR only)."""

import uuid
from pathlib import Path

from pageout.core.ir import plain_text
from pageout.renderers.base import R
from pageout.renderers.html import blocks_html, esc


def build_epub(title: str, icon_text: str, rows: list, tree, r: R, path: str, cfg: dict) -> None:
    """Build an EPUB file using the python-epub-build library."""
    try:
        from ebooklib import epub
    except ImportError:
        raise Exception("EPUB export needs: pip install ebooklib")

    # Create book
    book = epub.EpubBook()

    # Set metadata
    book.set_identifier(str(uuid.uuid4()))
    book.set_title(title)
    book.set_language(cfg.get("epub_language", "en"))

    # Author (from config or default)
    author = cfg.get("epub_author", "PageOut for Notion")
    book.add_author(author)

    # Description
    desc = cfg.get("epub_description", "Notion export")
    if desc:
        book.add_metadata("DC", "description", desc)

    # Publisher
    publisher = cfg.get("epub_publisher", "PageOut for Notion")
    book.add_metadata("DC", "publisher", publisher)

    # Create CSS style
    style = cfg.get("custom_css", "") or _EPUB_CSS
    nav_css = epub.EpubItemcss()
    nav_css = epub.EpubItem(
        id="style", file_name="style/nav.css", media_type="text/css", content=style if style else _EPUB_CSS
    )
    book.add_item(nav_css)

    # Create table of contents
    toc = epub.EpubHtml(
        title="Table of Contents",
        file_name="toc.xhtml",
        lang=cfg.get("epub_language", "en"),
        content=_build_toc(title, rows, cfg),
    )
    book.add_item(toc)

    # Main content
    img_counter = [0]
    body_content = blocks_html(tree, r, img_counter)
    if cfg.get("cover_page"):
        icon_html = _page_icon_html(icon_text, cfg)
        body_content = icon_html + body_content

    main_content = _EPUB_PAGE_TEMPLATE.format(title=esc(title), body=body_content)

    main_item = epub.EpubHtml(
        title=title, file_name="content.xhtml", lang=cfg.get("epub_language", "en"), content=main_content
    )
    book.add_item(main_item)

    # Add chapter items for sub-pages
    chapters = []
    for sub in _extract_chapters(tree):
        chap = epub.EpubHtml(
            title=sub["title"],
            file_name=f"chapter-{sub['id']}.xhtml",
            lang=cfg.get("epub_language", "en"),
            content=_build_chapter(sub, cfg),
        )
        book.add_item(chap)
        chapters.append(chap)

    # Define spine
    book.spine = ["nav", toc] + [main_item] + chapters

    # Define navigation
    nav = epub.EpubNav()
    nav_content = _build_nav(title, chapters)
    nav = epub.EpubNav()
    book.add_item(nav)

    # Build and write
    import shutil

    # Write to a temporary directory
    tmp_dir = Path(path).parent / f".epub_tmp_{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    try:
        epub.write_epub(path, book, {})
    finally:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)


_EPUB_CSS = """
@charset "UTF-8";
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0 1.5cm; }
h1, h2, h3 { color: #37352f; }
h1 { border-bottom: 2px solid #37352f; padding-bottom: 0.3em; }
h2 { border-bottom: 1px solid #d1d5db; padding-bottom: 0.2em; }
p { margin: 0.8em 0; }
code { background: #f4f4f4; padding: 0.2em 0.4em; border-radius: 3px; font-family: Consolas, monospace; }
pre { background: #f4f4f4; padding: 1em; border-radius: 5px; overflow-x: auto; }
"""

_EPUB_PAGE_TEMPLATE = """<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en">
<head>
    <meta charset="UTF-8" />
    <title>{title}</title>
    <link rel="stylesheet" type="text/css" href="style/nav.css" />
</head>
<body>
{body}
</body>
</html>
"""


def _page_icon_html(icon_text: str, cfg: dict) -> str:
    """Return HTML for page icon."""
    mode = cfg.get("icon_mode", "Show page icon")
    if mode == "Hide icon" or not icon_text:
        return ""
    return f'<p class="page-icon">{esc(icon_text)}&nbsp;</p>'


def _build_toc(title: str, rows: list, cfg: dict) -> str:
    """Build table of contents page."""
    lines = [f"<h1>{esc(title)}</h1>", '<ol class="toc">']
    for k, v in rows:
        lines.append(f"<li><span>{esc(k)}: </span><span>{esc(v)}</span></li>")
    lines.append("</ol>")

    return f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en">
<head>
    <meta charset="UTF-8" />
    <title>Table of Contents</title>
    <link rel="stylesheet" type="text/css" href="style/nav.css" />
</head>
<body>
{"".join(lines)}
</body>
</html>"""


def _build_nav(title: str, chapters: list) -> str:
    """Build navigation page."""
    if not chapters:
        return f"""<!DOCTYPE html>
<html>
<head><title>Navigation</title></head>
<body><h1>{esc(title)}</h1><p>No chapters.</p></body>
</html>"""

    toc_items = "".join(f'<li><a href="chapter-{c["id"]}.xhtml">{esc(c["title"])}</a></li>' for c in chapters)
    return f"""<!DOCTYPE html>
<html>
<head><title>Navigation</title></head>
<body><h1>{esc(title)}</h1><ol>{toc_items}</ol></body>
</html>"""


def _extract_chapters(tree) -> list:
    """Extract chapters from the block tree."""
    chapters = []

    def walk_blocks(blocks, depth=0):
        for b in blocks:
            if b.kind == "heading" and b.level == 1:
                # Found a potential chapter heading
                chapters.append({"id": str(len(chapters) + 1), "title": plain_text(b.text), "blocks": b.children or []})
            elif b.kind == "child_page" and b.sub:
                chapters.append({"id": str(len(chapters) + 1), "title": b.sub.title, "blocks": b.sub.blocks})
            walk_blocks(b.children, depth + 1)

    walk_blocks(tree)
    return chapters


def _build_chapter(chapter: dict, cfg: dict) -> str:
    """Build chapter content."""
    r = R(cfg, "epub")
    img_counter = [0]
    body = blocks_html(chapter.get("blocks", []), r, img_counter)
    return f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en">
<head>
    <meta charset="UTF-8" />
    <title>{esc(chapter["title"])}</title>
    <link rel="stylesheet" type="text/css" href="../style/nav.css" />
</head>
<body>
<h1>{esc(chapter["title"])}</h1>
{body}
</body>
</html>
"""
